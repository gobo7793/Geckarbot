import datetime
import logging

from base import BaseSubsystem
from botutils import restclient
from subsystems import timers
from subsystems.timers import Job


class CoroRegistration:
    def __init__(self, league_reg, coro = None, coro_kickoff = None, coro_finished = None, periodic: bool = False):
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
        match_list = self.league_reg.get_matches()
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
        self.timer_jobs = self.schedule_kickoffs()

    def register(self, coro, coro_kickoff, coro_finished, periodic: bool):
        reg = CoroRegistration(self, coro, coro_kickoff, coro_finished, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
        return reg

    def deregister(self):
        for job in self.timer_jobs:
            job.cancel()
        self.listener.deregister(self)

    def deregister_coro(self, coro: CoroRegistration):
        if coro in self.registrations:
            self.registrations.remove(coro)

    def get_matches(self, matchday=None):
        """Returns the current standings of the league"""
        if matchday:
            return restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}/2020/{}".format(
                self.league, matchday))
        else:
            matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(
                self.league))
            if self.extract_times(matches):
                return matches
            else:
                md = self.extract_matchday(matches)
                if md:
                    return self.get_matches(matchday=md + 1)

    def extract_times(self, m_list):
        t = []
        for match in m_list:
            try:
                kickoff = datetime.datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                continue
            else:
                if kickoff not in t:
                    if datetime.datetime.now() < (kickoff + datetime.timedelta(seconds=7200)):
                        t.append(kickoff)
        return t

    def extract_matchday(self, m_list):
        for match in m_list:
            md = match.get('Group', {}).get('GroupOrderID')
            if md is not None:
                break
        else:
            return None
        return md

    def get_kickoff_times(self, matchday=None):
        match_list = self.get_matches(matchday)
        times = self.extract_times(match_list)
        return times

    def schedule_kickoffs(self):
        """
        Schedules timers for the kickoffs of all matches

        :return: List of jobs
        """
        jobs = []
        kickoffs = self.get_kickoff_times()
        for time in kickoffs:
            jobs.append(self.listener.bot.timers.schedule(coro=self.schedule_match_timers, td=timers.timedict(
                year=time.year, month=time.month, monthday=time.day, hour=time.hour, minute=time.minute)))
        return jobs

    async def schedule_match_timers(self, job):
        self.logger.debug("Match in League {} started.".format(self.league))
        matches = self.get_matches()
        match_dicts = []
        now = datetime.datetime.now()
        for m in matches[:]:
            try:
                kickoff = datetime.datetime.strptime(m.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                continue
            else:
                self.logger.debug(kickoff)
                if kickoff.date() == now.date() and kickoff.hour == now.hour and kickoff.minute == now.minute:
                    match_dicts.append({
                        "team_home": m.get('Team1', {}).get('TeamName'),
                        "team_away": m.get('Team2', {}).get('TeamName'),
                    })
        for coro_reg in self.registrations:
            await coro_reg.update_kickoff(match_dicts)
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
        return job1, job2

    def next_match(self):
        """Returns datetime of the next match"""
        if self.timer_jobs:
            return min(job.next_execution() for job in self.timer_jobs if job)
        else:
            return None

    async def update_periodic_coros(self, job: Job = None):
        """

        :param job:
        :return:
        """
        for coro_reg in self.registrations:
            if coro_reg.periodic:
                await coro_reg.update(job)

    def __str__(self):
        return "<liveticker.LeagueRegistration; league={}; regs={}>".format(self.league, len(self.registrations))


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
