import asyncio
import operator
from threading import Thread
from typing import List, Dict, Optional
from abc import ABC, abstractmethod
from datetime import datetime

import discord
from espn_api.football import League

from botutils.converters import get_best_user
from botutils.restclient import Client
from botutils.timeutils import from_epoch_ms
from botutils.jsonutils import Decoder
from conf import Storage, Config, Lang
from plugins.fantasy.utils import Activity, TeamStanding, Team, Player, Match, Platform, log


def set_flex_pos_name(slot_position_old):
    if "RB/WR".lower() in slot_position_old.lower():
        return "FLEX"
    return slot_position_old


def create_league(plugin, platform: Platform, league_id: int, commish: discord.User = None, init=False):
    """
    Creates a FantasyLeague object based on the given platform

    :param plugin: The fantasy plugin instance
    :param platform: The Platform on which the league is hosted
    :param league_id: The league ID on the platform
    :param commish: The commissioner
    :param init: True if league is loading from Storage
    :return: The created FantasyLeague object for the given platform
    """
    if platform == Platform.ESPN:
        return EspnLeague(plugin, league_id, commish, init)
    if platform == Platform.Sleeper:
        return SleeperLeague(plugin, league_id, commish, init)


def deserialize_league(plugin, d: dict):
    """
    Constructs a FantasyLeague object based on the platform saved in the dict.

    :param plugin: The plugin instance
    :param d: dict made by FantasyLeague.serialize()
    :return: FantasyLeague object
    """
    return create_league(plugin, d["platform"], d['league_id'], get_best_user(d['commish']), init=True)


class FantasyLeague(ABC):
    """Fatasy Football League dataset"""

    def __init__(self, plugin, league_id: int, commish: discord.User = None, init=False):
        """
        Creates a new FantasyLeague dataset instance

        :param plugin: The fantasy plugin instance
        :param league_id: The league ID on the platform
        :param commish: The commissioner
        :param init: True if league is loading from Storage
        """
        self.plugin = plugin
        self.league_id = league_id
        self.commish = commish

        if init:
            connect_thread = Thread(target=self._load_league_data)
            connect_thread.start()
        else:
            self._load_league_data()

    @abstractmethod
    def _load_league_data(self):
        """Login and load league data from hosting platform"""
        pass

    def __str__(self):
        return "<fantasy.FantasyLeague; league_id: {}, commish: {}, platform: {}>".format(
            self.league_id, self.commish, self.platform)

    @abstractmethod
    def reload(self):
        """Reloads cached league data from host platform"""
        pass

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Gets the league name"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Gets the league name"""
        pass

    @property
    @abstractmethod
    def year(self) -> int:
        """Gets the current fantasy football year"""
        pass

    @property
    @abstractmethod
    def current_week(self) -> int:
        """Gets the current fantasy football week"""
        pass

    @property
    @abstractmethod
    def nfl_week(self) -> int:
        """Gets the current NFL week"""
        pass

    @property
    @abstractmethod
    def trade_deadline(self) -> str:
        """Gets the tradeline week"""
        return Lang.lang(self.plugin, "unknown")

    @property
    @abstractmethod
    def league_url(self) -> str:
        """Gets the home page url for the league"""
        pass

    @property
    @abstractmethod
    def scoreboard_url(self) -> str:
        """Gets the scoreboard page url"""
        pass

    @property
    @abstractmethod
    def standings_url(self) -> str:
        """Gets the standings page url"""
        pass

    @abstractmethod
    def get_boxscore_url(self, week=0, teamid=0) -> str:
        """Gets the boxscore page url for given week and team id"""
        pass

    @abstractmethod
    def get_teams(self) -> List[Team]:
        """
        Gets all teams and their names and IDs only

        :return: A list with Team tuples
        """
        pass

    @abstractmethod
    def get_boxscores(self, week, match_id=-1) -> List[Match]:
        """
        Returns the boxscore data for the given match ID or all matches in given week of current year

        :param week: The week to get the boxscores from
        :param match_id: The match ID of the match, or -1 for all matches
        :return: The Boxscores as List of Match tuples
        """
        pass

    @abstractmethod
    def get_overall_standings(self) -> List[TeamStanding]:
        """
        Gets the current overall league standing

        :return: A list with TeamStanding tuples for the overall standing
        """
        pass

    @abstractmethod
    def get_divisional_standings(self) -> Dict[str, List[TeamStanding]]:
        """
        Gets the current standings of each division of the league

        :return: The divisional standings with a list of TeamStanding tuples for each division
        """
        pass

    @abstractmethod
    def get_most_recent_activity(self):
        """
        Gets the most recent activity.

        :return: An Activity tuple or None if platform doesn't support recent activities
        """
        pass

    def serialize(self):
        """
        Serializes the league dataset to a dict

        :return: A dict with the espn_id and commish
        """
        return {
            'platform': self.platform,
            'league_id': self.league_id,
            'commish': self.commish.id
        }


class EspnLeague(FantasyLeague):

    def __init__(self, plugin, league_id: int, commish: discord.User = None, init=False):
        self._espn = None  # type: Optional[League]

        FantasyLeague.__init__(self, plugin, league_id, commish, init)

    def _load_league_data(self):
        self._espn = League(year=self.plugin.year, league_id=self.league_id,
                            espn_s2=Config.get(self.plugin)["espn_credentials"]["espn_s2"],
                            swid=Config.get(self.plugin)["espn_credentials"]["swid"])
        log.info("League {}, ID {} on platform ESPN connected".format(self.name, self.league_id))

    def reload(self):
        self._espn.refresh()

    @property
    def platform(self) -> Platform:
        return Platform.ESPN

    @property
    def name(self) -> str:
        return self._espn.settings.name

    @property
    def year(self) -> int:
        return self._espn.year

    @property
    def current_week(self) -> int:
        return self._espn.current_week

    @property
    def nfl_week(self) -> int:
        return self._espn.nfl_week

    @property
    def trade_deadline(self) -> str:
        return from_epoch_ms(self._espn.settings.trade_deadline).strftime(Lang.lang(self.plugin, "until_strf"))

    @property
    def league_url(self) -> str:
        return Config.get(self.plugin)["espn"]["url_base_league"].format(self.league_id)

    @property
    def scoreboard_url(self) -> str:
        return Config.get(self.plugin)["espn"]["url_base_scoreboard"].format(self.league_id)

    @property
    def standings_url(self) -> str:
        return Config.get(self.plugin)["espn"]["url_base_standings"].format(self.league_id)

    def get_boxscore_url(self, week=0, teamid=0) -> str:
        if week == 0:
            week = self.current_week
        if teamid == 0:
            teamid = 1
        return Config.get(self.plugin)["espn"]["url_base_boxscore"].format(
            self.league_id, week, self._espn.year, teamid)

    def get_teams(self) -> List[Team]:
        teams = []
        for t in self._espn.teams:
            teams.append(Team(t.team_name, t.team_abbrev, t.team_id, 0))
        return teams

    def get_boxscores(self, week, match_id=-1) -> List[Match]:
        boxscores = self._espn.box_scores(week)
        matches = []
        for i in range(len(boxscores)):
            if match_id > -1 and match_id != i:
                continue
            score = boxscores[i]
            home_team, away_team = None, None
            home_lineup, away_lineup = [], []

            if score.home_team is not None and score.home_team != 0:
                home_team = Team(score.home_team.team_name, score.home_team.team_abbrev, score.home_team.team_id, 0)
            if score.away_team is not None and score.away_team != 0:
                away_team = Team(score.away_team.team_name, score.away_team.team_abbrev, score.away_team.team_id, 0)

            for hp in score.home_lineup:
                home_lineup.append(Player(set_flex_pos_name(hp.slot_position), hp.name, hp.proTeam,
                                          hp.projected_points, hp.points))
            for al in score.away_lineup:
                away_lineup.append(Player(set_flex_pos_name(al.slot_position), al.name, al.proTeam,
                                          al.projected_points, al.points))

            matches.append(Match(home_team, score.home_score, home_lineup,
                                 away_team, score.away_score, away_lineup))
        return matches

    def get_overall_standings(self) -> List[TeamStanding]:
        standings = []
        for team in self._espn.standings():
            wins = int(team.wins)
            losses = int(team.losses)
            record = wins / (wins + losses)
            standing = TeamStanding(team.team_name, wins, losses, record, float(team.points_for))
            standings.append(standing)
        return standings

    def get_divisional_standings(self) -> Dict[str, List[TeamStanding]]:
        divisions = {}
        for team in self._espn.standings():
            if team.division_name not in divisions:
                divisions[team.division_name] = []
            wins = int(team.wins)
            losses = int(team.losses)
            record = wins / (wins + losses)
            standing = TeamStanding(team.team_name, wins, losses, record, float(team.points_for))
            divisions[team.division_name].append(standing)
        return divisions

    def get_most_recent_activity(self):
        activities = self._espn.recent_activity()
        act_date = from_epoch_ms(activities[0].date)
        act_team = activities[0].actions[0][0].team_name
        act_type = activities[0].actions[0][1]
        act_player = activities[0].actions[0][2]
        return Activity(act_date, str(act_team), str(act_type), str(act_player))


class SleeperLeague(FantasyLeague):

    player_db_key = "sleeper_players"
    last_db_call_key = "_last_call"

    def __init__(self, plugin, league_id: int, commish: discord.User = None, init=False):
        self._client = Client("https://api.sleeper.app/v1/")
        self._league_data = {}
        self._teams = []

        FantasyLeague.__init__(self, plugin, league_id, commish, init)

    def _load_league_data(self):
        self.reload()
        log.info("League {}, ID {} on platform Sleeper connected".format(self.name, self.league_id, self.platform))

    async def _load_player_db(self):
        last_call = Storage.get(self.plugin, self.player_db_key)\
            .get(self.last_db_call_key, datetime.min)
        if last_call.date() >= datetime.now().date():
            log.debug("Sleepers player database shouldn't downloaded more than once per day.")
            return

        log.info("Getting Sleepers player database. This shouldn't be done more than once per day!")
        players_json = await self._client.request(endpoint="players/nfl", parse_json=False)
        players = Decoder().decode(players_json)
        players[self.last_db_call_key] = datetime.now()
        Storage.set(self.plugin, players, self.player_db_key)
        Storage.save(self.plugin, self.player_db_key)

    def reload(self):
        self._league_data = self._client.make_request(endpoint="league/{}".format(self.league_id))
        rosters = self._client.make_request(endpoint="league/{}/rosters".format(self.league_id))
        users = self._client.make_request(endpoint="league/{}/users".format(self.league_id))
        if not self.plugin.bot.DEBUG_MODE:
            asyncio.run_coroutine_threadsafe(self._load_player_db, self.plugin.bot.loop)

        self._teams = []
        for roster in rosters:
            team_name = ""
            user_name = ""
            for user in users:
                if user["user_id"] == roster["owner_id"]:
                    user_name = user["display_name"]
                    team_name = user.get("metadata", {}).get("team_name", user_name)
            team = Team(team_name, user_name, roster["roster_id"], roster["owner_id"])
            self._teams.append(team)

    @property
    def platform(self) -> Platform:
        return Platform.Sleeper

    @property
    def name(self) -> str:
        return self._league_data["name"]

    @property
    def year(self) -> int:
        try:
            year = int(self._league_data["season"])
            return year
        except (TypeError, ValueError):
            return self.plugin.year

    @property
    def current_week(self) -> int:
        return self._league_data["settings"]["leg"]

    @property
    def nfl_week(self) -> int:
        return self._league_data["settings"]["leg"]

    @property
    def trade_deadline(self) -> str:
        return "{} {}".format(Lang.lang(self.plugin, "week"), self._league_data["settings"]["trade_deadline"])

    @property
    def league_url(self) -> str:
        return Config.get(self.plugin)["sleeper"]["url_base_league"].format(self.league_id)

    @property
    def scoreboard_url(self) -> str:
        return Config.get(self.plugin)["sleeper"]["url_base_scoreboard"].format(self.league_id)

    @property
    def standings_url(self) -> str:
        return Config.get(self.plugin)["sleeper"]["url_base_standings"].format(self.league_id)

    def get_boxscore_url(self, week=0, teamid=0) -> str:
        return Config.get(self.plugin)["sleeper"]["url_base_boxscore"].format(self.league_id)

    def get_teams(self) -> List[Team]:
        return self._teams

    def get_boxscores(self, week, match_id=-1) -> List[Match]:
        # Doesn't support boxscores yet (12/2020), so match_id isn't used

        if week < 1 or week > self.current_week:
            week = self.current_week
        matchups_raw = self._client.make_request(endpoint="league/{}/matchups/{}".format(self.league_id, week))
        matches = {}
        for matchup in matchups_raw:
            home_match = None
            if matchup["matchup_id"] in matches.keys():
                home_match = matches[matchup["matchup_id"]]
            score = matchup["points"]
            team = next(t for t in self.get_teams() if t.team_id == matchup["roster_id"])

            if home_match is None:
                matches[matchup["matchup_id"]] = Match(team, score, [], None, None, [])
            else:
                matches[matchup["matchup_id"]] = Match(home_match.home_team, home_match.home_score, [],
                                                       team, score, [])

        return list(matches.values())

    def get_overall_standings(self) -> List[TeamStanding]:
        rosters = self._client.make_request(endpoint="league/{}/rosters".format(self.league_id))
        sleeper_standings = []
        for roster in rosters:
            team = next(t for t in self.get_teams() if t.team_id == roster["roster_id"])
            wins = roster["settings"]["wins"]
            losses = roster["settings"]["losses"]
            ties = roster["settings"]["ties"]
            record = (wins + 0.5 * ties) / (wins + losses + ties)
            pts_for = roster["settings"]["fpts"] + (roster["settings"]["fpts_decimal"] / 100)
            standing = TeamStanding(team.team_name, wins, losses, record, pts_for)
            sleeper_standings.append(standing)
        sleeper_standings.sort(key=operator.itemgetter(4), reverse=True)
        sleeper_standings.sort(key=operator.itemgetter(3), reverse=True)
        return sleeper_standings

    def get_divisional_standings(self) -> Dict[str, List[TeamStanding]]:
        return {Lang.lang(self.plugin, "overall"): self.get_overall_standings()}

    def get_most_recent_activity(self):
        transactions = self._client.make_request(
            endpoint="league/{}/transactions/{}".format(self.league_id, self.current_week))
        transactions.extend(self._client.make_request(
            endpoint="league/{}/transactions/{}".format(self.league_id, self.current_week - 1)))
        if not transactions:
            return None
        for action in transactions:
            if action["status"] != "complete":
                continue
            act_date = from_epoch_ms(action["status_updated"])
            act_type = "ADD" if action["drops"] is None else "DROP"
            act_roster_id = list(action["adds"].values())[0] \
                if act_type == "ADD" else list(action["drops"].values())[0]
            player_id = list(action["adds"].keys())[0] \
                if act_type == "ADD" else list(action["drops"].keys())[0]
            act_team = next(t for t in self.get_teams() if t.team_id == act_roster_id)
            act_player = Storage.get(self.plugin, self.player_db_key)[player_id]
            player_name = act_player["full_name"]

            return Activity(act_date, act_team.team_name, act_type, player_name)
