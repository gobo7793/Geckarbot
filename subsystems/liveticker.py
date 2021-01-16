import datetime
import logging

from base import BaseSubsystem
from botutils import restclient
from conf import Storage
from subsystems import timers
from subsystems.timers import Job


class CoroRegistration:
    def __init__(self, league_reg, plugin, coro=None, coro_kickoff=None, coro_finished=None, periodic: bool = False):
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
        self.coro_kickoff = coro_kickoff
        self.coro_finished = coro_finished
        self.periodic = periodic
        self.last_goal = {}
        self.logger = logging.getLogger(__name__)

    def deregister(self):
        if self.storage() in Storage().get(self.league_reg.listener)['registrations'][self.league_reg.league]:
            Storage().get(self.league_reg.listener)['registrations'][self.league_reg.league].remove(self.storage())
            Storage().save(self.league_reg.listener)
        self.league_reg.deregister_coro(self)

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

    async def update(self, job: Job):
        minute = (datetime.datetime.now() - job.data['start']).seconds // 60
        if minute > 45:
            minute = max(45, minute - 15)
        await self.coro(self.get_match_dicts(), self.league_reg.league, minute)

    async def update_kickoff(self, data):
        if self.coro_kickoff:
            match_dicts = [convert_to_matchdict(m) for m in data['matches']]
            await self.coro_kickoff(match_dicts, self.league_reg.league, data['start'])

    async def update_finished(self, match_list):
        if self.coro_finished:
            match_dicts = [convert_to_matchdict(m) for m in match_list]
            await self.coro_finished(match_dicts, self.league_reg.league)

    def storage(self):
        return {
            'plugin': self.plugin_name,
            'coro': self.coro.__name__ if self.coro else None,
            'coro_kickoff': self.coro_kickoff.__name__ if self.coro_kickoff else None,
            'coro_finished': self.coro_finished.__name__ if self.coro_finished else None,
            'periodic': self.periodic
        }

    def __eq__(self, other):
        return self.coro == other.coro and self.coro_kickoff == other.coro_kickoff and\
               self.coro_finished == other.coro_finished and self.periodic == other.periodic

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; coro_kickoff={}; coro_finished={}; periodic={}>"\
            .format(self.coro, self.coro_kickoff, self.coro_finished, self.periodic)


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

    def register(self, plugin, coro, coro_kickoff, coro_finished, periodic: bool):
        """Registers a CoroReg for this league"""
        reg = CoroRegistration(self, plugin, coro, coro_kickoff, coro_finished, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
            Storage().get(self.listener)['registrations'][self.league].append(reg.storage())
            Storage().save(self.listener)
        return reg

    def deregister(self):
        """Deregisters this LeagueReg correctly"""
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
        if self.league in Storage().get(self.listener)['registrations']:
            Storage().get(self.listener)['registrations'].pop(self.league)
            Storage().save(self.listener)
        self.listener.deregister(self)

    def deregister_coro(self, coro: CoroRegistration):
        if coro in self.registrations:
            self.registrations.remove(coro)

    def update_matches(self, matchday=None):
        """Updates the matches and current standings of the league"""
        if matchday:
            self.matches = restclient.Client("https://www.openligadb.de/api").make_request(
                "/getmatchdata/{}/2020/{}".format(self.league, matchday))
        else:
            self.matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(
                self.league))
            if not self.extract_kickoffs_with_matches():
                md = self.extract_matchday()
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

    def extract_matchday(self):
        for match in self.matches:
            md = match.get('Group', {}).get('GroupOrderID')
            if md is not None:
                break
        else:
            return None
        return md

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
        job.data['matches'] = self.extract_kickoffs_with_matches()[datetime.datetime.now().replace(second=0,
                                                                                                   microsecond=0)]
        await self.update_kickoff_coros(job)
        self.schedule_timers(start=datetime.datetime.now())

    def schedule_timers(self, start: datetime.datetime):
        """
        Schedules timers in 15-minute intervals during the match starting 15 minutes after the beginning and stopping 2
        hours after

        :param start: start datetime of the match
        :return: jobs objects of the timers
        """
        minutes = [m + (start.minute % 15) for m in range(0, 60, 15)]
        intermediate = timers.timedict(year=[start.year], month=[start.month], monthday=[start.day], minute=minutes)
        job = self.listener.bot.timers.schedule(coro=self.update_periodic_coros, td=intermediate, data={'start': start})
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
        """Returns datetime of the next timer execution"""
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


class Liveticker(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.registrations = {}

    def default_storage(self):
        return {
            'registrations': {}
        }

    def register(self, league, plugin, coro, coro_kickoff=None, coro_finished=None, periodic: bool = False):
        """

        :param plugin:
        :param coro_kickoff:
        :param coro_finished:
        :param league:
        :param coro:
        :param periodic:
        :return: LeagueRegistration, CoroRegistration
        """
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league)
        if league not in Storage().get(self)['registrations']:
            Storage().get(self)['registrations'][league] = []
            Storage().save(self)
        coro_reg = self.registrations[league].register(plugin, coro, coro_kickoff, coro_finished, periodic)
        return self.registrations[league], coro_reg

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
