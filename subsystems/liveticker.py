import datetime
import logging

from base import BaseSubsystem
from botutils import restclient
from subsystems import timers
from subsystems.timers import Job


class CoroRegistration:
    def __init__(self, league_reg, coro, periodic: bool):
        """
        Registration for a single Coroutine

        :param league_reg:
        :type league_reg: LeagueRegistration
        :param coro:
        :param periodic:
        """
        self.league_reg = league_reg
        self.coro = coro
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
                         if g.get('MatchMinute', 0) > self.last_goal.get(match_id, 0)]
            score = (max(0, 0, *(g.get('ScoreTeam1', 0) for g in match.get('Goals', []))),
                     max(0, 0, *(g.get('ScoreTeam2', 0) for g in match.get('Goals', []))))
            match_dict[match_id] = {
                "team_home": match.get('Team1', {}).get('TeamName'),
                "team_away": match.get('Team2', {}).get('TeamName'),
                "score": score,
                "new_goals": new_goals
            }
            self.last_goal[match_id] = max(self.last_goal.get(match_id, 0), 0,
                                           *(g.get('MatchMinute', 0) for g in match.get('Goals', [])))
        return match_dict

    async def update(self, job: Job):
        self.logger.debug("", job.next_execution())
        await self.coro(self.get_new_goals())

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; periodic={}>".format(self.coro, self.periodic)

class LeagueRegistration:
    def __init__(self, listener, league):
        self.listener = listener
        self.league = league
        self.registrations = []

    def register(self, coro, periodic: bool):
        reg = CoroRegistration(self, coro, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
        return reg

    def deregister(self):
        self.listener.deregister(self)

    def deregister_coro(self, coro: CoroRegistration):
        if coro in self.registrations:
            self.registrations.remove(coro)

    def get_matches(self):
        """Returns the current standings of the league"""
        return restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(self.league))

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
        return job1, job2

    async def update_periodic_coros(self, job: Job):
        """

        :param job:
        :return:
        """
        for coro_reg in self.registrations:
            if coro_reg.periodic:
                await coro_reg.update()

    def __str__(self):
        return "<liveticker.LeagueRegistration; league={}; regs={}>".format(self.league, len(self.registrations))

class Liveticker(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.registrations = {}

    def register(self, league, coro, periodic: bool = True):
        """

        :param league:
        :param coro:
        :param periodic:
        :return: LeagueRegistration, CoroRegistration
        """
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league)
        coro_reg = self.registrations[league].register(coro, periodic)
        return self.registrations[league], coro_reg

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
