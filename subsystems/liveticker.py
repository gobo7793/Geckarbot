from base import BaseSubsystem
from botutils import restclient


class CoroRegistration:
    def __init__(self, league_reg, coro, periodic: bool):
        """

        :param league_reg:
        :type league_reg: LeagueRegistration
        :param coro:
        :param periodic:
        """
        self.league_reg = league_reg
        self.coro = coro
        self.periodic = periodic
        self.last_goal = {}

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

    def __str__(self):
        return "<liveticker.LeagueRegistration; league={}; regs={}>".format(self.league, len(self.registrations))

class Liveticker(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.registrations = {}

    def register(self, league, coro, periodic: bool = True):
        if league not in self.registrations:
            self.registrations[league] = LeagueRegistration(self, league)
        return self.registrations[league].register(coro, periodic)

    def deregister(self, reg: LeagueRegistration):
        if reg.league in self.registrations:
            self.registrations.pop(reg.league)
