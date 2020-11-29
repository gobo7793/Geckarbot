import datetime
import logging

from base import BaseSubsystem
from botutils import restclient
from subsystems import timers
from subsystems.timers import Job


class CoroRegistration:
    def __init__(self, league_reg, coro=None, coro_kickoff=None, coro_finished=None, periodic: bool = False):
        """
        Registration for a single Coroutine

        :param league_reg:
        :type league_reg: LeagueRegistration
        :param coro:
        :param periodic:
        """
        self.league_reg = league_reg
        self.coro = coro
        self.coro_kickoff = coro_kickoff
        self.coro_finished = coro_finished
        self.periodic = periodic
        self.last_goal = {}
        self.logger = logging.getLogger(__name__)

    def deregister(self):
        self.league_reg.deregister_coro(self)

    def get_new_goals(self):
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
            match_dict[match_id] = {
                "team_home": match.get('Team1', {}).get('TeamName'),
                "team_away": match.get('Team2', {}).get('TeamName'),
                "score": score,
                "new_goals": new_goals,
                "is_finished": match.get('MatchIsFinished')
            }
            if not self.last_goal.get(match_id):
                self.last_goal[match_id] = []
            self.last_goal[match_id] += [g.get('GoalID') for g in new_goals]
        return match_dict

    async def update(self, job: Job = None):
        self.logger.debug("Updated {}".format(str(self)))
        await self.coro(self.get_new_goals())
        self.logger.debug("Updated {} successfully?!".format(str(self)))

    async def update_kickoff(self, match_dicts):
        await self.coro_kickoff(match_dicts)

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; periodic={}>".format(self.coro, self.periodic)


class LeagueRegistration:
    def __init__(self, listener, league):
        self.listener = listener
        self.league = league
        self.registrations = []
        self.logger = logging.getLogger(__name__)
        self.kickoff_timers = []
        self.intermediate_timers = []
        self.matches = []

        self.update_matches()
        self.schedule_kickoffs()

    def register(self, coro, coro_kickoff, coro_finished, periodic: bool):
        reg = CoroRegistration(self, coro, coro_kickoff, coro_finished, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
        return reg

    def deregister(self):
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
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
            if not self.extract_kickoffs():
                md = self.extract_matchday()
                if md:
                    self.update_matches(matchday=md + 1)
        return self.matches

    def extract_matches_by_kickoff(self, time: datetime.datetime):
        match_dicts = []
        for m in self.matches:
            try:
                kickoff = datetime.datetime.strptime(m.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                continue
            else:
                if kickoff.date() == time.date() and kickoff.hour == time.hour and kickoff.minute == time.minute:
                    match_dicts.append({
                        "team_home": m.get('Team1', {}).get('TeamName'),
                        "team_away": m.get('Team2', {}).get('TeamName'),
                    })
        return match_dicts

    def extract_kickoffs(self):
        t = []
        for match in self.matches:
            try:
                kickoff = datetime.datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                continue
            else:
                if kickoff not in t:
                    if datetime.datetime.now() < (kickoff + datetime.timedelta(seconds=7200)):
                        t.append(kickoff)
        return t

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
        kickoffs = self.extract_kickoffs()
        now = datetime.datetime.now()
        for time in kickoffs:
            if time > now:
                # Upcoming match
                jobs.append(self.listener.bot.timers.schedule(coro=self.schedule_match_timers, td=timers.timedict(
                    year=time.year, month=time.month, monthday=time.day, hour=time.hour, minute=time.minute)))
            else:
                # Running match
                self.schedule_timers(start=time)
                tmp_job = self.listener.bot.timers.schedule(coro=self.update_kickoff_coros, td=timers.timedict())
                tmp_job.data = self.extract_matches_by_kickoff(time)
                tmp_job.execute()
        self.kickoff_timers.extend(jobs)
        return jobs

    async def schedule_match_timers(self, job=None):
        self.logger.debug("Match in League {} started.".format(self.league))
        job.data = self.extract_matches_by_kickoff(datetime.datetime.now())
        await self.update_kickoff_coros(job)
        self.schedule_timers(start=datetime.datetime.now())

    def schedule_timers(self, start: datetime.datetime):
        """
        Schedules timers in 15-minute intervals during the match starting 15 minutes after the beginning and stopping 2
        hours after

        :param start: start datetime of the match
        :return: jobs objects of the timers
        """
        minutes = list(range(start.minute + 15, start.minute + 75, 15))
        minutes_1 = [x for x in minutes if x < 60]
        minutes_2 = [x % 60 for x in minutes if x >= 60]

        job1 = None
        job2 = None
        if minutes_1:
            intermediate = timers.timedict(year=[start.year], month=[start.month], monthday=[start.day],
                                           hour=[start.hour, start.hour + 1],
                                           minute=minutes_1)
            job1 = self.listener.bot.timers.schedule(coro=self.update_periodic_coros, td=intermediate)
        if minutes_2:
            intermediate = timers.timedict(year=[start.year], month=[start.month], monthday=[start.day],
                                           hour=[start.hour + 1, start.hour + 2],
                                           minute=minutes_2)
            job2 = self.listener.bot.timers.schedule(coro=self.update_periodic_coros, td=intermediate)
        self.logger.debug("Timers for match starting at {} scheduled.".format(start.strftime("%d/%m/%Y %H:%M")))
        self.intermediate_timers.extend((job1, job2))
        return job1, job2

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

    async def update_periodic_coros(self, job: Job = None):
        """

        :param job:
        :return:
        """
        self.update_matches()
        for coro_reg in self.registrations:
            if coro_reg.periodic:
                await coro_reg.update(job)

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

    def register(self, league, coro, coro_kickoff=None, coro_finished=None, periodic: bool = False):
        """

        :param coro_kickoff:
        :param coro_finished:
        :param league:
        :param coro:
        :param periodic:
        :return: LeagueRegistration, CoroRegistration
        """
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league)
        coro_reg = self.registrations[league].register(coro, coro_kickoff, coro_finished, periodic)
        return self.registrations[league], coro_reg

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
