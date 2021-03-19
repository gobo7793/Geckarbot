import datetime
import logging
from enum import Enum

from base import BaseSubsystem
from botutils import restclient
from botutils.converters import get_plugin_by_name
from data import Storage
from subsystems import timers
from subsystems.timers import Job


class LTSource(Enum):
    OPENLIGADB = "oldb"
    ESPN = "espn"


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

    @staticmethod
    def match_status_oldb(m):
        if m.get('MatchIsFinished'):
            return MatchStatus.COMPLETED
        else:
            try:
                kickoff = datetime.datetime.strptime(m.get('MatchDateTimeUTC'), "%Y-%m-%dT%H:%M:%SZ") \
                    .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
            except (ValueError, TypeError):
                return MatchStatus.UNKNOWN
            else:
                if kickoff < datetime.datetime.now():
                    return MatchStatus.RUNNING
                else:
                    return MatchStatus.UPCOMING


class Match:
    def __init__(self, match_id, kickoff, minute, home_team, home_team_id, away_team, away_team_id, is_completed,
                 status, raw_events, score=None, new_events=None):
        if new_events is None:
            new_events = []
        self.match_id = match_id
        self.kickoff = kickoff
        self.minute = minute
        self.home_team = home_team
        self.home_team_id = home_team_id
        self.away_team = away_team
        self.away_team_id = away_team_id
        self.status = status
        self.is_completed = is_completed
        self.raw_events = raw_events
        self.new_events = new_events
        if score:
            self.score = score
        else:
            self.score = {self.home_team_id: 0, self.away_team_id: 0}

    @classmethod
    def from_openligadb(cls, m, new_events=None):
        # Extract kickoff into datetime object
        if new_events is None:
            new_events = []
        try:
            kickoff = datetime.datetime.strptime(m.get('MatchDateTimeUTC'), "%Y-%m-%dT%H:%M:%SZ")\
                .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        except (ValueError, TypeError):
            kickoff = None
        # Calculate current minute
        if kickoff:
            minute = (datetime.datetime.now() - kickoff).seconds // 60
            if minute > 45:
                minute = max(45, minute - 15)
        else:
            minute = None
        # Note team IDs
        home_id = m.get('Team1', {}).get('TeamId')
        away_id = m.get('Team2', {}).get('TeamId')

        match = cls(match_id=m.get('MatchID'),
                    kickoff=kickoff,
                    minute=minute,
                    home_team=m.get('Team1', {}).get('TeamName'),
                    home_team_id=home_id,
                    away_team=m.get('Team2', {}).get('TeamName'),
                    away_team_id=away_id,
                    score={home_id: max(0, 0, *(g.get('ScoreTeam1', 0) for g in m.get('Goals', []))),
                           away_id: max(0, 0, *(g.get('ScoreTeam2', 0) for g in m.get('Goals', [])))},
                    is_completed=m.get('MatchIsFinished'),
                    raw_events=m.get('Goals'),
                    status=MatchStatus.match_status_oldb(m),
                    new_events=new_events)
        match.matchday = m.get('Group', {}).get('GroupOrderID')
        return match

    @classmethod
    def from_espn(cls, m, new_events=None):
        # Extract kickoff into datetime object
        try:
            kickoff = datetime.datetime.strptime(m.get('date'), "%Y-%m-%dT%H:%MZ")\
                .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
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
                    new_events=new_events,
                    raw_events=m.get('competitions', [{}])[0].get('details'),
                    status=MatchStatus.match_status_espn(m))
        return match

class PlayerEvent:
    def __init__(self, event_id, player, minute):
        self.event_id = event_id
        self.player = player
        self.minute = minute

    def display(self):
        pass


class Goal(PlayerEvent):
    def __init__(self, event_id, player, minute, score, is_owngoal, is_penalty):
        super().__init__(event_id, player, minute)
        self.score = score
        self.is_owngoal = is_owngoal
        self.is_penalty = is_penalty

    @classmethod
    def from_openligadb(cls, g: dict, home_id, away_id):
        goal = cls(event_id=g.get('GoalID'),
                   player=g.get('GoalGetterName'),
                   minute=g.get('MatchMinute'),
                   score={home_id: g.get('ScoreTeam1'),
                          away_id: g.get('ScoreTeam2')},
                   is_owngoal=g.get('IsOwnGoal'),
                   is_penalty=g.get('IsPenalty'))
        goal.is_overtime = g.get('IsOvertime')
        return goal

    @classmethod
    def from_espn(cls, g: dict, score: dict):
        score[g.get('team', {}).get('id')] += g.get('scoreValue')
        goal = cls(event_id="{}/{}/{}".format(g.get('type', {}).get('id'),
                                              g.get('clock', {}).get('value'),
                                              g.get('athletesInvolved', [{}])[0].get('id')),
                   player=g.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=g.get('clock', {}).get('displayValue'),
                   score=score,
                   is_owngoal=g.get('ownGoal'),
                   is_penalty=g.get('penaltyKick'))
        return goal

    def display(self):
        return ":soccer: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)


class YellowCard(PlayerEvent):
    @classmethod
    def from_espn(cls, rc):
        return cls(event_id="{}/{}/{}".format(rc.get('type', {}).get('id'),
                                              rc.get('clock', {}).get('value'),
                                              rc.get('athletesInvolved', [{}])[0].get('id')),
                   player=rc.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=rc.get('clock', {}).get('displayValue'))

    def display(self):
        return ":yellow_square: {} ({})".format(self.player, self.minute)


class RedCard(PlayerEvent):
    def __init__(self, event_id, player, minute):
        super().__init__(event_id, player, minute)

    @classmethod
    def from_espn(cls, rc):
        return cls(event_id="{}/{}/{}".format(rc.get('type', {}).get('id'),
                                              rc.get('clock', {}).get('value'),
                                              rc.get('athletesInvolved', [{}])[0].get('id')),
                   player=rc.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=rc.get('clock', {}).get('displayValue'))

    def display(self):
        return ":red_square: {} ({})".format(self.player, self.minute)

def build_player_event(event, score):
    if event.get('scoringPlay'):
        return Goal.from_espn(event, score)
    elif event.get('type', {}).get('id') == "93":
        return RedCard.from_espn(event)
    elif event.get('type', {}).get('id') == "94":
        return YellowCard.from_espn(event)


class LivetickerEvent:
    def __init__(self, league, matches):
        self.league = league
        self.matches = matches


class LivetickerKickoff(LivetickerEvent):
    def __init__(self, league, matches, kickoff):
        super().__init__(league, matches)
        self.kickoff = kickoff


class LivetickerUpdate(LivetickerEvent):
    def __init__(self, league, matches, new_events):
        m_list = []
        for m in matches:
            m.new_events = new_events.get(m.match_id)
            m_list.append(m)
        super().__init__(league, m_list)


class LivetickerFinish(LivetickerEvent):
    def __init__(self, league, matches):
        super().__init__(league, matches)


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
        self.last_events = {}
        self.logger = logging.getLogger(__name__)

    def deregister(self):
        self.league_reg.deregister_coro(self)

    def unload(self):
        self.league_reg.unload_coro(self)

    def next_kickoff(self):
        """Returns datetime of the next match"""
        return self.league_reg.next_kickoff()

    def next_execution(self):
        """Returns datetime of the next timer execution"""
        return self.league_reg.next_execution()

    async def update(self, job):
        self.logger.debug("CoroReg updates.")
        matches = self.league_reg.extract_kickoffs_with_matches()[job.data['start']]
        new_events = {}
        for m in matches:
            if m.match_id not in self.last_events:
                self.last_events[m.match_id] = []
            events = []
            if self.league_reg.source == LTSource.OPENLIGADB:
                for g in m.raw_events:
                    goal = Goal.from_openligadb(g, m.home_team_id, m.away_team_id)
                    if goal.event_id not in self.last_events[m.match_id]:
                        events.append(goal)
            elif self.league_reg.source == LTSource.ESPN:
                tmp_score = {m.home_team_id: 0, m.away_team_id: 0}
                for e in m.raw_events:
                    event = build_player_event(e, tmp_score.copy())
                    if type(event) == Goal:
                        tmp_score = event.score
                    if event.event_id not in self.last_events[m.match_id]:
                        events.append(event)
            new_events[m.match_id] = events
            self.last_events[m.match_id].extend([e.event_id for e in events])
        await self.coro(LivetickerUpdate(self.league_reg.league, matches, new_events))

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


class LeagueRegistration:
    def __init__(self, listener, league, source: LTSource):
        self.listener = listener
        self.league = league
        self.source = source
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
            if reg_storage not in Storage().get(self.listener)[self.source.value][self.league]:
                Storage().get(self.listener)[self.source.value][self.league].append(reg_storage)
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
        if reg_storage in Storage().get(self.listener)[self.source.value].get(self.league, []):
            Storage().get(self.listener)[self.source.value][self.league].remove(reg_storage)
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
        if self.source == LTSource.OPENLIGADB:
            self._update_matches_oldb(matchday)
        elif self.source == LTSource.ESPN:
            self._update_matches_espn()
        return self.matches

    def _update_matches_oldb(self, matchday=None):
        if matchday:
            raw_matches = restclient.Client("https://www.openligadb.de/api").make_request(
                "/getmatchdata/{}/2020/{}".format(self.league, matchday))
            self.matches = [Match.from_openligadb(m) for m in raw_matches]
        elif self.matchday():
            if self.next_execution():
                self._update_matches_oldb(matchday=self.matchday())
            else:
                self._update_matches_oldb(matchday=self.matchday() + 1)
                self.schedule_kickoffs()
        else:
            raw_matches = restclient.Client("https://www.openligadb.de/api").make_request(
                "/getmatchdata/{}".format(self.league))
            self.matches = [Match.from_openligadb(m) for m in raw_matches]
            if not self.extract_kickoffs_with_matches():
                md = self.matchday()
                if md:
                    self._update_matches_oldb(matchday=md + 1)

    def _update_matches_espn(self):
        raw = restclient.Client("http://site.api.espn.com/apis/site/v2/sports").make_request(
            f"/soccer/{self.league}/scoreboard")
        self.matches = [Match.from_espn(m) for m in raw.get('events', [])]

    def extract_kickoffs_with_matches(self):
        kickoff_dict = {}
        for match in self.matches:
            if match.kickoff is None:  # Unknown kickoff
                if None not in kickoff_dict:
                    kickoff_dict[None] = []
                kickoff_dict[None].append(match)
            elif match.kickoff in kickoff_dict:  # Insert at kickoff
                kickoff_dict[match.kickoff].append(match)
            elif match.status != MatchStatus.COMPLETED:
                kickoff_dict[match.kickoff] = [match]
        return kickoff_dict

    def matchday(self):
        if self.source == LTSource.OPENLIGADB:
            for match in self.matches:
                md = match.matchday
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
        interval = 15
        minutes = [m + (start.minute % interval) for m in range(0, 60, interval)]
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
            self.finished.extend([m.match_id for m in matches])
        else:
            for match in matches:
                if match.is_completed and match.match_id not in self.finished:
                    new_finished.append(match)
                    self.finished.append(match.match_id)
        for coro_reg in self.registrations:
            if coro_reg.periodic:
                await coro_reg.update(job)
            if new_finished:
                await coro_reg.update_finished(new_finished)
        if len([m for m in matches if m.match_id not in self.finished]) == 0:
            job.cancel()

    def __str__(self):
        next_exec = self.next_execution()
        if next_exec:
            next_exec = next_exec[0].strftime('%Y-%m-%d - %H:%M'), next_exec[1]
        return f"<liveticker.LeagueRegistration; league={self.league}; src={self.source.value}; " \
               f"regs={len(self.registrations)}; next={next_exec}>"

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
        regs = {}
        for src in LTSource.__members__.values():
            regs[src.value] = {}
        return regs

    def register(self, league, raw_source, plugin, coro, periodic: bool = True):
        """
        Registers a new liveticker for the specified league.

        :param raw_source: which data source should be used (espn, oldb etc.)
        :param plugin: plugin where all coroutines are in
        :param league: League the liveticker should observe
        :param coro: coroutine for the events
        :param periodic: if coro should be updated automatically
        :return: CoroRegistration
        """
        source = LTSource(raw_source)
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league, source)
        if league not in Storage().get(self)[source.value]:
            Storage().get(self)[source.value][league] = []
            Storage().save(self)
        coro_reg = self.registrations[league].register(plugin, coro, periodic)
        return coro_reg

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
        if reg.league in Storage().get(self)[reg.source.value]:
            Storage().get(self)[reg.source.value].pop(reg.league)
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
        for src, registrations in Storage().get(self).items():
            for league in registrations:
                for reg in registrations[league]:
                    if reg['plugin'] in plugins:
                        i += 1
                        coro = getattr(get_plugin_by_name(reg['plugin']),
                                       reg['coro']) if reg['coro'] else None
                        self.register(plugin=get_plugin_by_name(reg['plugin']),
                                      league=league,
                                      raw_source=src,
                                      coro=coro,
                                      periodic=reg['periodic'])
        self.logger.debug(f'{i} Liveticker registrations restored.')

    def unload_plugin(self, plugin_name):
        coro_dict = self.search(plugin=plugin_name)
        for leag in coro_dict.values():
            for reg in leag:
                reg.unload()
        self.logger.debug(f'Liveticker for plugin {plugin_name} unloaded')
