import datetime
import logging
from enum import Enum

from base import BaseSubsystem
from botutils import restclient
from botutils.converters import get_plugin_by_name
from data import Storage
from subsystems import timers
from subsystems.timers import Job


class MatchStatus(Enum):
    COMPLETED = ":ballot_box_with_check:"
    RUNNING = ":green_square:"
    UPCOMING = ":clock4:"
    POSTPONED = ":no_entry_sign:"
    UNKNOWN = "❔"

    @staticmethod
    def match_status_espn(m):
        status = m.get('status', {}).get('type', {}).get('state')
        if status == "pre":
            return MatchStatus.UPCOMING
        elif status == "in":
            return MatchStatus.RUNNING
        elif status == "post":
            if m.get('status', {}).get('type', {}).get('completed'):
                return MatchStatus.COMPLETED
            else:
                return MatchStatus.POSTPONED
        return MatchStatus.UNKNOWN


class Match:
    def __init__(self, match_id, kickoff, minute, home_team, home_team_id, away_team, away_team_id, is_completed,
                 score=None, new_goals=None):
        if new_goals is None:
            new_goals = []
        self.match_id = match_id
        self.kickoff = kickoff
        self.minute = minute
        self.home_team = home_team
        self.home_team_id = home_team_id
        self.away_team = away_team
        self.away_team_id = away_team_id
        self.is_completed = is_completed
        self.new_goals = new_goals
        if score:
            self.score = score
        else:
            self.score = {self.home_team_id: 0, self.away_team_id: 0}

    @classmethod
    def from_openligadb(cls, m):
        try:
            kickoff = datetime.datetime.strptime(m.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            kickoff = None
        if kickoff:
            minute = (datetime.datetime.now() - kickoff).seconds // 60
            if minute > 45:
                minute = max(45, minute - 15)
        else:
            minute = None

        match = cls(match_id=m.get('MatchID'),
                    kickoff=kickoff,
                    minute=minute,
                    home_team=m.get('Team1', {}).get('TeamName'),
                    home_team_id=m.get('Team1', {}).get('TeamId'),
                    away_team=m.get('Team2', {}).get('TeamName'),
                    away_team_id=m.get('Team2', {}).get('TeamId'),
                    is_completed=m.get('MatchIsFinished'))
        return match

    @classmethod
    def from_openligadb_int(cls, m, new_goals):
        match = cls.from_openligadb(m)
        match.new_goals = new_goals
        match.score[match.home_team_id] = max(0, 0, *(g.get('ScoreTeam1', 0) for g in match.get('Goals', [])))
        match.score[match.away_team_id] = max(0, 0, *(g.get('ScoreTeam2', 0) for g in match.get('Goals', [])))
        return match

    @classmethod
    def from_espn(cls, m, new_goals=None):
        # Extract kickoff into datetime object
        try:
            kickoff = datetime.datetime.strptime(m.get('date'), "%Y-%m-%dT%H:%MZ")
        except (ValueError, TypeError):
            kickoff = None
        # Get home and away team
        home_team, away_team, home_id, away_id, home_score, away_score = None, None, None, None, None, None
        for team in m.get('competitions', [{}])[0].get('competitors'):
            if team.get('homeAway') == "home":
                home_team = team.get('team', {}).get('displayName')
                home_id = team.get('id')
                home_score = team.get('score')
            elif team.get('homeAway') == "away":
                away_team = team.get('team', {}).get('displayName')
                away_id = team.get('id')
                away_score = team.get('score')

        # Put all informations together
        match = cls(match_id=m.get('uid'),
                    kickoff=kickoff,
                    minute=m.get('status', {}).get('displayClock'),
                    home_team=home_team,
                    home_team_id=home_id,
                    away_team=away_team,
                    away_team_id=away_id,
                    is_completed=m.get('status', {}).get('type', {}).get('completed'),
                    score={home_id: home_score, away_id: away_score},
                    new_goals=new_goals)
        return match

class PlayerEvent:
    def __init__(self, player, minute):
        self.player = player
        self.minute = minute


class Goal(PlayerEvent):
    def __init__(self, player, minute, score, is_owngoal, is_penalty):
        super().__init__(player, minute)
        self.score = score
        self.is_owngoal = is_owngoal
        self.is_penalty = is_penalty

    @classmethod
    def from_openligadb(cls, g: dict):
        goal = cls(player=g.get('GoalGetterName'),
                   minute=g.get('MatchMinute'),
                   score={g.get('Team1', {}).get('TeamId'): g.get('ScoreTeam1'),
                          g.get('Team2', {}).get('TeamId'): g.get('ScoreTeam2')},
                   is_owngoal=g.get('IsOwnGoal'),
                   is_penalty=g.get('IsPenalty'))
        goal.goal_id = g.get('GoalID')
        goal.is_overtime = g.get('IsOvertime')
        return goal

    @classmethod
    def from_espn(cls, g: dict, score: dict):
        score[g.get('team', {}).get('id')] = g.get('scoreValue')
        goal = cls(player=g.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=g.get('clock', {}).get('displayValue'),
                   score=score,
                   is_owngoal=g.get('ownGoal'),
                   is_penalty=g.get('penaltyKick'))
        return goal


class RedCard(PlayerEvent):
    def __init__(self, player, minute):
        super().__init__(player, minute)

    @classmethod
    def from_espn(cls, redcard):
        return cls(player=redcard.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=redcard.get('clock', {}).get('displayValue'))


class LivetickerEvent:
    def __init__(self, league, matches):
        self.league = league
        self.matches = matches


class LivetickerKickoff(LivetickerEvent):
    def __init__(self, league, matches, kickoff):
        super().__init__(league, [Match.from_openligadb(m) for m in matches])
        self.kickoff = kickoff


class LivetickerUpdate(LivetickerEvent):
    def __init__(self, league, matches, ng):
        m_list = []
        for m in matches:
            new_goals = ng.get(m.get('MatchID'))
            m_list.append(Match.from_openligadb_int(m, new_goals))
        super().__init__(league, m_list)


class LivetickerFinish(LivetickerEvent):
    def __init__(self, league, matches):
        super().__init__(league, [Match.from_openligadb(m) for m in matches])


class CoroRegistration:
    def __init__(self, league_reg, plugin, coro, periodic: bool = False):
        """
        Registration for a single Coroutine

        :param league_reg:
        :type league_reg: LeagueRegistration
        :param coro:
        :param periodic:
        """
        self.league_reg = league_reg
        self.plugin_name = plugin.get_name()
        self.coro = coro
        self.periodic = periodic
        self.last_goal = {}
        self.logger = logging.getLogger(__name__)

    def deregister(self):
        self.league_reg.deregister_coro(self)

    def unload(self):
        self.league_reg.unload_coro(self)

    def get_match_dicts(self):
        """Builds the dictionarys for each match"""
        match_list = self.league_reg.matches
        match_dict = {}
        for match in match_list:
            match_id = match.get('MatchID')
            if match_id is None:
                continue
            new_goals = [g for g in match.get('Goals', [])
                         if g.get('GoalID', 0) not in self.last_goal.get(match_id, [])]
            score = (max(0, 0, *(g.get('ScoreTeam1', 0) for g in match.get('Goals', []))),
                     max(0, 0, *(g.get('ScoreTeam2', 0) for g in match.get('Goals', []))))
            try:
                kickoff = datetime.datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                kickoff = None
            match_dict[match_id] = {
                "team_home": match.get('Team1', {}).get('TeamName'),
                "team_away": match.get('Team2', {}).get('TeamName'),
                "score": score,
                "new_goals": new_goals,
                "kickoff_time": kickoff,
                "is_finished": match.get('MatchIsFinished')
            }
            if not self.last_goal.get(match_id):
                self.last_goal[match_id] = []
            self.last_goal[match_id] += [g.get('GoalID') for g in new_goals]
        return match_dict

    def next_kickoff(self):
        """Returns datetime of the next match"""
        return self.league_reg.next_kickoff()

    def next_execution(self):
        """Returns datetime of the next timer execution"""
        return self.league_reg.next_execution()

    async def update(self, job):
        matches = self.league_reg.extract_kickoffs_with_matches()[job.data['start']]
        new_goals = {}
        for m in matches:
            m_id = m.get('MatchID')
            if m_id not in self.last_goal:
                self.last_goal[m_id] = []
            ng = [g for g in m.get('Goals', []) if g.get('GoalID', 0) not in self.last_goal[m_id]]
            new_goals[m_id] = ng
            self.last_goal[m_id].extend([g.get('GoalID', 0) for g in ng])
        event = LivetickerUpdate(self.league_reg.league, matches, new_goals)
        await self.coro(event)

    async def update_kickoff(self, data):
        await self.coro(LivetickerKickoff(self.league_reg.league, data['matches'], data['start']))

    async def update_finished(self, match_list):
        await self.coro(LivetickerFinish(self.league_reg.league, match_list))

    def storage(self):
        return {
            'plugin': self.plugin_name,
            'coro': self.coro.__name__,
            'periodic': self.periodic
        }

    def __eq__(self, other):
        return self.coro == other.coro and self.periodic == other.periodic

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; periodic={}>" \
            .format(self.coro, self.periodic)

    def __bool__(self):
        return bool(self.next_execution())


def convert_to_matchdict(match):
    return {
        "team_home": match.get('Team1', {}).get('TeamName'),
        "team_away": match.get('Team2', {}).get('TeamName'),
    }


class LeagueRegistration:
    def __init__(self, listener, league):
        self.listener = listener
        self.league = league
        self.registrations = []
        self.logger = logging.getLogger(__name__)
        self.kickoff_timers = []
        self.intermediate_timers = []
        self.matches = []
        self.finished = []

        self.update_matches()
        self.schedule_kickoffs()

    def register(self, plugin, coro, periodic: bool):
        """Registers a CoroReg for this league"""
        reg = CoroRegistration(self, plugin, coro, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
            reg_storage = reg.storage()
            if reg_storage not in Storage().get(self.listener)['registrations'][self.league]:
                Storage().get(self.listener)['registrations'][self.league].append(reg_storage)
                Storage().save(self.listener)
        return reg

    def deregister(self):
        """Deregisters this LeagueReg correctly"""
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
        self.listener.deregister(self)

    def unload(self):
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
        self.listener.unload(self)

    def deregister_coro(self, coro: CoroRegistration):
        reg_storage = coro.storage()
        if reg_storage in Storage().get(self.listener)['registrations'].get(self.league, []):
            Storage().get(self.listener)['registrations'][self.league].remove(reg_storage)
            Storage().save(self.listener)
        if coro in self.registrations:
            self.registrations.remove(coro)
        if not self.registrations:
            self.deregister()

    def unload_coro(self, coro: CoroRegistration):
        if coro in self.registrations:
            self.registrations.remove(coro)
        if not self.registrations:
            self.unload()

    def update_matches(self, matchday=None):
        """Updates the matches and current standings of the league"""
        if matchday:
            self.matches = restclient.Client("https://www.openligadb.de/api").make_request(
                "/getmatchdata/{}/2020/{}".format(self.league, matchday))
        elif self.matchday():
            if self.next_execution():
                self.update_matches(matchday=self.matchday())
            else:
                self.update_matches(matchday=self.matchday() + 1)
                self.schedule_kickoffs()
        else:
            self.matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(
                self.league))
            if not self.extract_kickoffs_with_matches():
                md = self.matchday()
                if md:
                    self.update_matches(matchday=md + 1)
        return self.matches

    def extract_kickoffs_with_matches(self):
        kickoff_dict = {}
        for match in self.matches:
            try:
                kickoff = datetime.datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                continue
            else:
                if kickoff in kickoff_dict:
                    kickoff_dict[kickoff].append(match)
                elif datetime.datetime.now() < (kickoff + datetime.timedelta(seconds=7200)):
                    kickoff_dict[kickoff] = [match]
        return kickoff_dict

    def matchday(self):
        for match in self.matches:
            md = match.get('Group', {}).get('GroupOrderID')
            if md:
                return md
        else:
            return None

    def schedule_kickoffs(self):
        """
        Schedules timers for the kickoffs of all matches

        :return: List of jobs
        """
        jobs = []
        kickoffs = self.extract_kickoffs_with_matches()
        now = datetime.datetime.now()
        for time in kickoffs:
            if time > now:
                # Upcoming match
                jobs.append(self.listener.bot.timers.schedule(coro=self.schedule_match_timers, td=timers.timedict(
                    year=time.year, month=time.month, monthday=time.day, hour=time.hour, minute=time.minute)))
            else:
                # Running match
                self.schedule_timers(start=time)
                tmp_job = self.listener.bot.timers.schedule(coro=self.update_kickoff_coros, td=timers.timedict(),
                                                            data={'start': time, 'matches': kickoffs[time]})
                tmp_job.execute()
        self.kickoff_timers.extend(jobs)
        return jobs

    async def schedule_match_timers(self, job):
        self.logger.debug("Match in League {} started.".format(self.league))
        now = datetime.datetime.now().replace(second=0, microsecond=0)
        job.data = {'start': now,
                    'matches': self.extract_kickoffs_with_matches()[now]}
        await self.update_kickoff_coros(job)
        self.schedule_timers(start=now)

    def schedule_timers(self, start: datetime.datetime):
        """
        Schedules timers in 15-minute intervals during the match starting 15 minutes after the beginning and stopping 2
        hours after

        :param start: start datetime of the match
        :return: jobs objects of the timers
        """
        minutes = [m + (start.minute % 3) for m in range(0, 60, 3)]
        intermediate = timers.timedict(year=[start.year], month=[start.month], monthday=[start.day], minute=minutes)
        job = self.listener.bot.timers.schedule(coro=self.update_periodic_coros, td=intermediate, data={'start': start})
        if job.next_execution().minute == datetime.datetime.now().minute:
            job.execute()
        self.logger.debug("Timers for match starting at {} scheduled.".format(start.strftime("%d/%m/%Y %H:%M")))
        self.intermediate_timers.append(job)
        return job

    def next_kickoff(self):
        """Returns datetime of the next match"""
        kickoffs = (i.next_execution() for i in self.kickoff_timers if i)
        if kickoffs:
            return min(kickoffs)
        else:
            return None

    def next_execution(self):
        """Returns datetime and type of the next timer execution"""
        kickoffs = [j for j in (i.next_execution() for i in self.kickoff_timers if i) if j]
        intermed = [j for j in (i.next_execution() for i in self.intermediate_timers if i) if j]
        if kickoffs and intermed:
            next_exec, timer_type = min((min(kickoffs), "kickoff"), (min(intermed), "intermediate"))
        elif kickoffs:
            next_exec, timer_type = min(kickoffs), "kickoff"
        elif intermed:
            next_exec, timer_type = min(intermed), "intermediate"
        else:
            return None
        return next_exec, timer_type

    async def update_kickoff_coros(self, job: Job):
        for coro_reg in self.registrations:
            await coro_reg.update_kickoff(job.data)
        job.cancel()

    async def update_periodic_coros(self, job: Job):
        """
        Regularly updates coros and checks if matches are still running.

        :param job:
        :return:
        """
        if job.data['start'] == datetime.datetime.now().replace(second=0, microsecond=0):
            return
        new_finished = []
        self.update_matches()
        matches = self.extract_kickoffs_with_matches()[job.data['start']]
        if (datetime.datetime.now() - job.data['start']).seconds > 9000:
            new_finished = matches
            self.finished.extend([m.get('MatchID') for m in matches])
        else:
            for match in matches:
                if match.get('MatchIsFinished') and match.get('MatchID') not in self.finished:
                    new_finished.append(match)
                    self.finished.append(match.get('MatchID'))
        for coro_reg in self.registrations:
            if coro_reg.periodic:
                await coro_reg.update(job)
            if new_finished:
                await coro_reg.update_finished(new_finished)
        if len([m for m in matches if m.get('MatchID') not in self.finished]) == 0:
            job.cancel()

    def __str__(self):
        next_exec = self.next_execution()
        if next_exec:
            next_exec = next_exec[0].strftime('%Y-%m-%d - %H:%M'), next_exec[1]
        return "<liveticker.LeagueRegistration; league={}; regs={}; next={}>".format(self.league,
                                                                                     len(self.registrations), next_exec)

    def __bool__(self):
        return bool(self.next_execution())


class Liveticker(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.registrations = {}
        self.restored = False

        @bot.listen()
        async def on_ready():
            plugins = self.bot.get_normalplugins()
            self.restore(plugins)
            self.restored = True

    def default_storage(self):
        return {
            'registrations': {}
        }

    def register(self, league, plugin, coro, periodic: bool = True):
        """
        Registers a new liveticker for the specified league.

        :param plugin: plugin where all coroutines are in
        :param league: League the liveticker should observe
        :param coro: coroutine for the events
        :param periodic: if coro should be updated automatically
        :return: CoroRegistration
        """
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league)
        if league not in Storage().get(self)['registrations']:
            Storage().get(self)['registrations'][league] = []
            Storage().save(self)
        coro_reg = self.registrations[league].register(plugin, coro, periodic)
        return coro_reg

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
        if reg.league in Storage().get(self)['registrations']:
            Storage().get(self)['registrations'].pop(reg.league)
            Storage().save(self)

    def unload(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)

    def search(self, plugin=None, league=None) -> dict:
        """
        Searches all CoroRegistrations fulfilling the requirements

        :param plugin: plugin name
        :param league: league key
        :return: Dictionary with a list of all matching registrations per league
        """
        if league:
            league_reg = self.registrations.get(league)
            if league_reg:
                coro_regs = [(league, self.registrations[league].registrations)]
            else:
                return {}
        else:
            coro_regs = [(leag.league, leag.registrations) for leag in self.registrations.values()]
        coro_dict = {}
        for leag, regs in coro_regs:
            r = [i for i in regs if plugin is None or i.plugin_name == plugin]
            if r:
                coro_dict[leag] = r
        return coro_dict

    def restore(self, plugins: list):
        i = 0
        registrations = Storage().get(self)['registrations']
        for league in registrations:
            for reg in registrations[league]:
                if reg['plugin'] in plugins:
                    i += 1
                    coro = getattr(get_plugin_by_name(reg['plugin']),
                                   reg['coro']) if reg['coro'] else None
                    self.register(plugin=get_plugin_by_name(reg['plugin']),
                                  league=league,
                                  coro=coro,
                                  periodic=reg['periodic'])
        self.logger.debug(f'{i} Liveticker registrations restored.')

    def unload_plugin(self, plugin_name):
        coro_dict = self.search(plugin=plugin_name)
        for leag in coro_dict.values():
            for reg in leag:
                reg.unload()
        self.logger.debug(f'Liveticker for plugin {plugin_name} unloaded')
