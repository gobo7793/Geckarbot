import logging
import operator
from collections import namedtuple
from datetime import datetime, timedelta
from enum import IntEnum
from threading import Thread
from typing import Dict, Optional, Union, List

import discord
from discord.ext import commands
from espn_api.football import League

import botutils.timeutils
from base import BasePlugin
from botutils import stringutils, permchecks
from botutils.converters import get_best_username, get_best_user
from botutils.timeutils import from_epoch_ms
from botutils.utils import add_reaction
from botutils.restclient import Client
from conf import Config, Storage, Lang
from subsystems import timers

# Repo link for pip package for ESPN API https://github.com/cwendt94/espn-api
# Sleeper API doc https://docs.sleeper.app/


log = logging.getLogger("fantasy")
pos_alphabet = {"Q": 0, "R": 1, "W": 2, "T": 3, "F": 4, "D": 5, "K": 6, "B": 7}
Activity = namedtuple("Activity", "date team_name type player_name")
TeamStanding = namedtuple("TeamStanding", "team_name wins losses record fpts")
Team = namedtuple("Team", "team_name team_abbrev team_id owner_id")
Player = namedtuple("Player", "slot_position name proTeam projected_points points")
Match = namedtuple("Match", "home_team home_score home_lineup away_team away_score away_lineup")


class FantasyState(IntEnum):
    """Fantasy states"""
    NA = 0
    Sign_up = 1
    Predraft = 2
    Preseason = 3
    Regular = 4
    Postseason = 5
    Finished = 6


class Platform(IntEnum):
    """Hosting platform of the fantasy league"""
    ESPN = 0
    Sleeper = 1


class FantasyLeague:
    """Fatasy Football League dataset"""

    def __init__(self, plugin, platform: Platform, league_id: int, commish: discord.User = None, init=False):
        """
        Creates a new FantasyLeague dataset instance

        :param plugin: The fantasy plugin instance
        :param platform: The fantasy league hosting platform
        :param league_id: The league ID on the platform
        :param commish: The commissioner
        :param init: True if league is loading from Storage
        """
        self.plugin = plugin
        self.platform = platform
        self.league_id = league_id
        self.commish = commish
        self._espn = None  # type: Optional[League]
        self._slc = None  # type: Optional[Client]
        self._sl_league_data = {}

        if init:
            connect_thread = Thread(target=self._load_league_data)
            connect_thread.start()
        else:
            self._load_league_data()

    def _load_league_data(self):
        """Login and load league data from hosting platform"""
        if self.platform == Platform.ESPN:
            self._espn = League(year=self.plugin.year, league_id=self.league_id,
                                espn_s2=Storage.get(self.plugin)["espn_credentials"]["espn_s2"],
                                swid=Storage.get(self.plugin)["espn_credentials"]["swid"])
        elif self.platform == Platform.Sleeper:
            self._slc = Client("https://api.sleeper.app/v1/")
            self.reload()
        log.info("League {}, ID {} on platform id {} connected".format(self.name, self.league_id, self.platform))

    def __str__(self):
        return "<fantasy.FantasyLeague; league_id: {}, commish: {}, platform: {}>".format(
            self.league_id, self.commish, self.platform)

    def reload(self):
        """Reloads cached league data from host platform"""
        if self.platform == Platform.ESPN:
            self._espn.refresh()
        elif self.platform == Platform.Sleeper:
            self._sl_league_data["league"] = self._slc.make_request(endpoint="league/{}".format(self.league_id))
            rosters = self._slc.make_request(endpoint="league/{}/rosters".format(self.league_id))
            users = self._slc.make_request(endpoint="league/{}/users".format(self.league_id))
            if not self.plugin.bot.DEBUG_MODE:
                players = self._slc.make_request(endpoint="players/nfl")
                Storage.set(self.plugin, players, "sleeper_players")
                Storage.save(self.plugin, "sleeper_players")

            self._sl_league_data["teams"] = []
            for roster in rosters:
                team_name = ""
                user_name = ""
                for user in users:
                    if user["user_id"] == roster["owner_id"]:
                        user_name = user["display_name"]
                        team_name = user.get("metadata", {}).get("team_name", user_name)
                team = Team(team_name, user_name, roster["roster_id"], roster["owner_id"])
                self._sl_league_data["teams"].append(team)

    @property
    def name(self) -> str:
        """Gets the league name"""
        if self.platform == Platform.ESPN:
            return self._espn.settings.name
        if self.platform == Platform.Sleeper:
            return self._sl_league_data["league"]["name"]
        return ""

    @property
    def year(self) -> int:
        """Gets the current fantasy football year"""
        if self.platform == Platform.ESPN:
            return self._espn.year
        if self.platform == Platform.Sleeper:
            try:
                year = int(self._sl_league_data["league"]["season"])
                return year
            except (TypeError, ValueError):
                pass
        return self.plugin.year

    @property
    def current_week(self) -> int:
        """Gets the current fantasy football week"""
        if self.platform == Platform.ESPN:
            return self._espn.current_week
        if self.platform == Platform.Sleeper:
            return self._sl_league_data["league"]["settings"]["leg"]
        return 1

    @property
    def nfl_week(self) -> int:
        """Gets the current NFL week"""
        if self.platform == Platform.ESPN:
            return self._espn.nfl_week
        if self.platform == Platform.Sleeper:
            return self._sl_league_data["league"]["settings"]["leg"]
        return 1

    @property
    def trade_deadline(self) -> int:
        """Gets the tradeline week"""
        if self.platform == Platform.ESPN:
            return self._espn.settings.trade_deadline
        if self.platform == Platform.Sleeper:
            return self._sl_league_data["league"]["settings"]["trade_deadline"]
        return 1

    @property
    def league_url(self) -> str:
        """Gets the home page url for the league"""
        if self.platform == Platform.ESPN:
            return Config.get(self.plugin)["espn"]["url_base_league"].format(self.league_id)
        if self.platform == Platform.Sleeper:
            return Config.get(self.plugin)["sleeper"]["url_base_league"].format(self.league_id)
        return ""

    @property
    def scoreboard_url(self) -> str:
        """Gets the scoreboard page url"""
        if self.platform == Platform.ESPN:
            return Config.get(self.plugin)["espn"]["url_base_scoreboard"].format(self.league_id)
        if self.platform == Platform.Sleeper:
            return Config.get(self.plugin)["sleeper"]["url_base_scoreboard"].format(self.league_id)
        return ""

    @property
    def standings_url(self) -> str:
        """Gets the standings page url"""
        if self.platform == Platform.ESPN:
            return Config.get(self.plugin)["espn"]["url_base_standings"].format(self.league_id)
        if self.platform == Platform.Sleeper:
            return Config.get(self.plugin)["sleeper"]["url_base_standings"].format(self.league_id)
        return ""

    def get_boxscore_url(self, week=0, teamid=0) -> str:
        """Gets the boxscore page url for given week and team id"""
        if self.platform == Platform.ESPN:
            if week == 0:
                week = self.current_week
            if teamid == 0:
                teamid = 1
            return Config.get(self.plugin)["espn"]["url_base_boxscore"].format(
                self.league_id, week, self._espn.year, teamid)
        if self.platform == Platform.Sleeper:
            return Config.get(self.plugin)["sleeper"]["url_base_boxscore"].format(self.league_id)
        return ""

    def get_teams(self) -> List[Team]:
        """
        Gets all teams and their names and IDs only

        :return: A list with Team tuples
        """
        if self.platform == Platform.ESPN:
            teams = []
            for t in self._espn.teams:
                teams.append(Team(t.team_name, t.team_abbrev, t.team_id, 0))
            return teams
        if self.platform == Platform.Sleeper:
            return self._sl_league_data["teams"]

    def get_boxscores(self, week) -> List[Match]:
        """
        Returns the boxscore data for all matches in given week of current year

        :param week: The week to get the boxscores from
        :return: The Boxscores as List of Match tuples
        """

        def pos_name(slot_position_old):
            if "RB/WR".lower() in hp.slot_position.lower():
                return "FLEX"
            return slot_position_old

        if self.platform == Platform.ESPN:
            boxscores = self._espn.box_scores(week)
            matches = []
            for score in boxscores:
                home_team = None
                away_team = None
                home_lineup = []
                away_lineup = []

                if score.home_team is not None and score.home_team != 0:
                    home_team = Team(score.home_team.team_name, score.home_team.team_abbrev, score.home_team.team_id, 0)
                if score.away_team is not None and score.away_team != 0:
                    away_team = Team(score.away_team.team_name, score.away_team.team_abbrev, score.away_team.team_id, 0)

                for hp in score.home_lineup:
                    home_lineup.append(Player(pos_name(hp.slot_position), hp.name, hp.proTeam,
                                              hp.projected_points, hp.points))
                for al in score.away_lineup:
                    away_lineup.append(Player(pos_name(al.slot_position), al.name, al.proTeam,
                                              al.projected_points, al.points))

                matches.append(Match(home_team, score.home_score, home_lineup,
                                     away_team, score.away_score, away_lineup))
            return matches

        if self.platform == Platform.Sleeper:
            if week < 1 or week > self.current_week:
                week = self.current_week
            matchups_raw = self._slc.make_request(endpoint="league/{}/matchups/{}".format(self.league_id, week))
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
        """
        Gets the current overall league standing

        :return: A list with TeamStanding tuples for the overall standing
        """
        if self.platform == Platform.ESPN:
            espn_standings = []
            for team in self._espn.standings():
                wins = int(team.wins)
                losses = int(team.losses)
                record = wins / (wins + losses)
                standing = TeamStanding(team.team_name, wins, losses, record, float(team.points_for))
                espn_standings.append(standing)
            return espn_standings

        if self.platform == Platform.Sleeper:
            rosters = self._slc.make_request(endpoint="league/{}/rosters".format(self.league_id))
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
        """
        Gets the current standings of each division of the league

        :return: The divisional standings with a list of TeamStanding tuples for each division
        """
        if self.platform == Platform.ESPN:
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
        if self.platform == Platform.Sleeper:
            return {Lang.lang(self.plugin, "overall"): self.get_overall_standings()}

    def get_most_recent_activity(self):
        """
        Gets the most recent activity.

        :return: An Activity tuple or None if platform doesn't support recent activities
        """
        if self.platform == Platform.ESPN:
            activities = self._espn.recent_activity()
            act_date = from_epoch_ms(activities[0].date)
            act_team = activities[0].actions[0][0].team_name
            act_type = activities[0].actions[0][1]
            act_player = activities[0].actions[0][2]
            return Activity(act_date, str(act_team), str(act_type), str(act_player))

        if self.platform == Platform.Sleeper:
            transactions = self._slc.make_request(
                endpoint="league/{}/transactions/{}".format(self.league_id, self.current_week))
            transactions.extend(self._slc.make_request(
                endpoint="league/{}/transactions/{}".format(self.league_id, self.current_week - 1)))
            if not transactions:
                return None
            for action in transactions:
                if action["status"] != "complete":
                    continue
                act_date = from_epoch_ms(action["status_updated"])
                act_type = "ADD" if action["drops"] is None else "DROP"
                act_roster_id = list(action["adds"].values())[0]\
                    if act_type == "ADD" else list(action["drops"].values())[0]
                player_id = list(action["adds"].keys())[0]\
                    if act_type == "ADD" else list(action["drops"].keys())[0]
                act_team = next(t for t in self.get_teams() if t.team_id == act_roster_id)
                act_player = Storage.get(self.plugin, "sleeper_players")[int(player_id)]
                player_name = act_player["full_name"]

                return Activity(act_date, act_team.team_name, act_type, player_name)

        return None

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

    @classmethod
    def deserialize(cls, plugin, d: dict):
        """
        Constructs a FantasyLeague object from a dict.

        :param plugin: The plugin instance
        :param d: dict made by serialize()
        :return: FantasyLeague object
        """
        return FantasyLeague(plugin, d['platform'], d['league_id'], get_best_user(d['commish']))


class Plugin(BasePlugin, name="NFL Fantasyliga"):
    """Commands for the Fantasy game"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.supercommish = None
        self.state = FantasyState.NA
        self.date = datetime.now()
        self.status = ""
        self.datalink = None
        self.start_date = datetime.now()
        self.end_date = datetime.now() + timedelta(days=16 * 7)
        self.use_timers = False
        self.leagues = []  # type: List[FantasyLeague]
        self._score_timer_jobs = []  # type: List[timers.Job]

        self._load()
        self._start_score_timer()

    def default_config(self):
        return {
            "version": 3,
            "channel_id": 0,
            "mod_role_id": 0,
            "espn": {
                "url_base_league": "https://fantasy.espn.com/football/league?leagueId={}",
                "url_base_scoreboard": "https://fantasy.espn.com/football/league/scoreboard?leagueId={}",
                "url_base_standings": "https://fantasy.espn.com/football/league/standings?leagueId={}",
                "url_base_boxscore":
                    "https://fantasy.espn.com/football/boxscore?leagueId={}&matchupPeriodId={}&seasonId={}&teamId={}"
            },
            "sleeper": {
                "url_base_league": "https://sleeper.app/leagues/{}",
                "url_base_scoreboard": "https://sleeper.app/leagues/{}/standings",
                "url_base_standings": "https://sleeper.app/leagues/{}/standings",
                "url_base_boxscore": "https://sleeper.app/leagues/{}/standings"
            }
        }

    def default_storage(self):
        return {
            "supercommish": 0,
            "state": FantasyState.NA,
            "date": datetime.now(),
            "status": "",
            "datalink": None,
            "start": datetime.now(),
            "end": datetime.now() + timedelta(days=16 * 7),
            "timers": False,
            "leagues": [],
            "espn_credentials": {
                "swid": "",
                "espn_s2": ""
            }
        }

    async def shutdown(self):
        self._stop_score_timer()
        self.leagues.clear()

    @property
    def year(self):
        return self.start_date.year

    def _load(self):
        """Loads the league settings from Storage"""
        if Config.get(self)["version"] == 2:
            self._update_config_from_2_to_3()
        if Config.get(self)["version"] == 3:
            self._update_config_from_3_to_4()

        self.supercommish = get_best_user(Storage.get(self)["supercommish"])
        self.state = Storage.get(self)["state"]
        self.date = Storage.get(self)["date"]
        self.status = Storage.get(self)["status"]
        self.datalink = Storage.get(self)["datalink"]
        self.start_date = Storage.get(self)["start"]
        self.end_date = Storage.get(self)["end"]
        self.use_timers = Storage.get(self)["timers"]
        for d in Storage.get(self)["leagues"]:
            self.leagues.append(FantasyLeague.deserialize(self, d))

    def save(self):
        """Saves the league settings to json"""
        storage_d = {
            "supercommish": self.supercommish.id if self.supercommish is not None else 0,
            "state": self.state,
            "date": self.date,
            "status": self.status,
            "datalink": self.datalink,
            "start": self.start_date,
            "end": self.end_date,
            "timers": self.use_timers,
            "leagues": [el.serialize() for el in self.leagues],
            "espn_credentials": {
                "swid": Storage.get(self)["espn_credentials"]["swid"],
                "espn_s2": Storage.get(self)["espn_credentials"]["espn_s2"]
            }
        }
        Storage.set(self, storage_d)
        Storage.save(self)
        Config.save(self)

    def _update_config_from_3_to_4(self):
        log.info("Updating config from version 3 to version 4")

        for league in Storage.get(self)["leagues"]:
            league['platform'] = Platform.ESPN
        Storage.get(self)["espn_credentials"] = Storage.get(self)["api"]

        new_cfg = self.default_config()
        new_cfg["channel_id"] = Config.get(self)["channel_id"]
        new_cfg["mod_role_id"] = Config.get(self)["mod_role_id"]
        new_cfg["espn"]["url_base_league"] = Config.get(self)["url_base_league"] + "{}"
        new_cfg["espn"]["url_base_scoreboard"] = Config.get(self)["url_base_scoreboard"] + "{}"
        new_cfg["espn"]["url_base_standings"] = Config.get(self)["url_base_standings"] + "{}"
        new_cfg["espn"]["url_base_boxscore"] = Config.get(self)["url_base_boxscore"]
        new_cfg["version"] = 4

        Config.set(self, new_cfg)
        Storage.save(self)
        Config.save(self)

        log.info("Update finished")

    def _update_config_from_2_to_3(self):
        log.info("Updating config from version 2 to version 3")

        Config.get(self)["url_base_boxscore"] = self.default_config()["url_base_boxscore"]
        Config.get(self)["version"] = 3
        Config.save(self)

        log.info("Update finished")

    def _start_score_timer(self):
        """
        Starts the timer for auto-send scores to channel.
        If timer is already started, timer will be cancelled and removed before restart.
        Timer will be started only if Config().DEBUG_MODE is False.
        """
        if not self.use_timers:
            return
        if self.bot.DEBUG_MODE:
            log.warning("DEBUG MODE is on, fantasy timers will not be started!")
            return

        self._stop_score_timer()

        year_range = list(range(self.start_date.year, self.end_date.year + 1))
        month_range = list(range(self.start_date.month, self.end_date.month + 1))
        timedict_12h = timers.timedict(year=year_range, month=month_range, weekday=[1, 5], hour=12, minute=0)
        timedict_sun = timers.timedict(year=year_range, month=month_range, weekday=7, hour=[18, 22], minute=45)
        timedict_mon = timers.timedict(year=year_range, month=month_range, weekday=1, hour=1, minute=45)
        timedict_tue = timers.timedict(year=year_range, month=month_range, weekday=2, hour=12, minute=0)
        self._score_timer_jobs = [
            self.bot.timers.schedule(self._score_send_callback, timedict_12h, repeat=True),
            self.bot.timers.schedule(self._score_send_callback, timedict_sun, repeat=True),
            self.bot.timers.schedule(self._score_send_callback, timedict_mon, repeat=True),
            self.bot.timers.schedule(self._score_send_callback, timedict_tue, repeat=True)
        ]
        self._score_timer_jobs[0].data = False  # True = previous week, False = current week
        self._score_timer_jobs[1].data = False
        self._score_timer_jobs[2].data = False
        self._score_timer_jobs[3].data = True

    def _stop_score_timer(self):
        """Cancels all timers for auto-send scores to channel"""
        for job in self._score_timer_jobs:
            job.cancel()

    @commands.group(name="fantasy", help="Get and manage information about the NFL Fantasy Game",
                    description="Get the information about the Fantasy Game or manage it. "
                                "Command only works in NFL fantasy channel, if set."
                                "Managing information is only permitted for modrole or organisator.")
    async def fantasy(self, ctx):
        if Config.get(self)['channel_id'] != 0 and Config.get(self)['channel_id'] != ctx.channel.id:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            raise commands.CheckFailure()

        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('fantasy info'))

    @fantasy.command(name="scores", help="Gets the matchup scores", usage="[week] [team]",
                     description="Gets the current machtup scores or the scores from the given week. "
                                 "If a team name or abbreviation is given, the boxscores for the team for "
                                 "the current or given week is returned.")
    async def scores(self, ctx, *args):
        week = 0
        team_name = None
        try:
            week = int(args[0])
            if len(args) > 1:
                team_name = " ".join(args[1:])
        except (IndexError, ValueError):
            if len(args) > 0:
                team_name = " ".join(args)

        await self._write_scores(channel=ctx.channel, week=week, team_name=team_name)

    async def _score_send_callback(self, job):
        """Callback method for the timer to auto-send current scores to fantasy channel"""
        channel = self.bot.get_channel(Config.get(self)['channel_id'])
        if channel is not None:
            await self._write_scores(channel=channel, show_errors=False, previous_week=job.data)

    async def _write_scores(self, *, channel: discord.TextChannel, week: int = 0, team_name: str = None,
                            show_errors=True, previous_week=False):
        """Send the current scores of given week to given channel"""
        if not self.leagues:
            if show_errors:
                await channel.send(Lang.lang(self, "no_leagues"))
            return

        is_team_in_any_league = False
        no_boxscore_data = None
        for league in self.leagues:
            lweek = week
            if week == 0:
                lweek = league.current_week
            if previous_week:
                lweek -= 1
            if lweek < 1:
                lweek = 1

            async with channel.typing():
                if team_name is None:
                    embed = self._get_league_score_embed(league, lweek)
                else:
                    team = next((t for t in league.get_teams()
                                 if team_name.lower() in t.team_name.lower()
                                 or t.team_abbrev.lower() == team_name.lower()), None)
                    if team is None:
                        continue
                    is_team_in_any_league = True
                    if league.platform == Platform.Sleeper:
                        no_boxscore_data = (team.team_name, "Sleeper", league.get_boxscore_url(week, team.team_id))
                        continue
                    embed = self._get_boxscore_embed(league, team, lweek)

            if embed is not None:
                await channel.send(embed=embed)

        if no_boxscore_data is not None:
            await channel.send(Lang.lang(self, "no_boxscore_data", no_boxscore_data[0],
                                         no_boxscore_data[1], no_boxscore_data[2]))
        if team_name is not None and not is_team_in_any_league:
            await channel.send(Lang.lang(self, "team_not_found", team_name))

    def _get_league_score_embed(self, league: FantasyLeague, week: int):
        """Builds the discord.Embed for scoring overview in league with all matches"""
        prefix = Lang.lang(self, "scores_prefix", league.name,
                           week if week <= league.current_week else league.current_week)
        embed = discord.Embed(title=prefix, url=league.scoreboard_url)

        match_no = 0
        bye_team = None
        bye_pts = 0
        for match in league.get_boxscores(week):
            if match.home_team is None or match.home_team == 0 or not match.home_team:
                bye_team = match.away_team.team_name
                bye_pts = match.away_score
                continue
            elif match.away_team is None or match.away_team == 0 or not match.away_team:
                bye_team = match.home_team.team_name
                bye_pts = match.home_score
                continue
            match_no += 1
            name_str = Lang.lang(self, "matchup_name", match_no)
            value_str = Lang.lang(self, "matchup_data", match.away_team.team_name, match.away_score,
                                  match.home_team.team_name, match.home_score)
            embed.add_field(name=name_str, value=value_str)

        if bye_team is not None:
            embed.add_field(name=Lang.lang(self, "on_bye"), value="{} ({:6.2f})".format(bye_team, bye_pts))

        return embed

    def _get_boxscore_embed(self, league: FantasyLeague, team, week: int):
        """Builds the discord.Embed for the boxscore for given team in given week"""
        match = next((b for b in league.get_boxscores(week)
                      if (b.home_team is not None and b.home_team.team_name.lower() == team.team_name.lower())
                      or (b.away_team is not None and b.away_team.team_name.lower() == team.team_name.lower())), None)
        if match is None:
            return

        opp_name = None
        opp_score = None
        if match.home_team == team:
            score = match.home_score
            lineup = match.home_lineup
            opp_name = None
            if match.away_team is not None:
                opp_name = match.away_team.team_name
                opp_score = match.away_score
        else:
            score = match.away_score
            lineup = match.away_lineup
            if match.home_team is not None:
                opp_name = match.home_team.team_name
                opp_score = match.home_score

        lineup = sorted(lineup, key=lambda word: [pos_alphabet.get(c, ord(c)) for c in word.slot_position])

        prefix = Lang.lang(self, "box_prefix", team.team_name, league.name, week)
        embed = discord.Embed(title=prefix, url=league.get_boxscore_url(week, team.team_id))

        msg = ""
        for pl in lineup:
            if pl.slot_position.lower() != "BE".lower():
                msg = "{}{}\n".format(msg, Lang.lang(self, "box_data", pl.slot_position, pl.name,
                                                     pl.proTeam, pl.projected_points, pl.points))
        msg = "{}\n{}".format(msg, Lang.lang(self, "box_suffix", score))

        embed.description = msg
        if opp_name is None:
            embed.set_footer(text=Lang.lang(self, "box_footer_bye"))
        else:
            embed.set_footer(text=Lang.lang(self, "box_footer", opp_name, opp_score))
        return embed

    @fantasy.command(name="standings", help="Gets the full current standings")
    async def standings(self, ctx):
        if not self.leagues:
            await ctx.send(Lang.lang(self, "no_leagues"))
            return

        for league in self.leagues:
            embed = discord.Embed(title=league.name)
            embed.url = league.standings_url

            async with ctx.typing():
                divisions = league.get_divisional_standings()
                for division in divisions:
                    div = divisions[division]
                    standing_str = "\n".join([
                        Lang.lang(self, "standings_data", t + 1, div[t].team_name, div[t].wins, div[t].losses)
                        for t in range(len(div))])
                    embed.add_field(name=division, value=standing_str)

            await ctx.send(embed=embed)

    @fantasy.command(name="info", help="Get information about the NFL Fantasy Game")
    async def info(self, ctx):
        if self.supercommish is None or not self.leagues:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "need_supercommish_leagues"))
            return

        date_out_str = Lang.lang(self, 'info_date_str', self.date.strftime(Lang.lang(self, "until_strf")))

        for league in self.leagues:
            embed = discord.Embed(title=league.name)
            embed.url = league.league_url

            embed.add_field(name=Lang.lang(self, "supercommish"), value=self.supercommish.mention)
            embed.add_field(name=Lang.lang(self, "commish"), value=league.commish.mention)

            async with ctx.typing():
                if self.state == FantasyState.Sign_up:
                    phase_lang = "signup_phase_info"
                    date_out_str = date_out_str if self.date > datetime.now() else ""
                    embed.add_field(name=Lang.lang(self, 'sign_up_at'), value=self.supercommish.mention)

                elif self.state == FantasyState.Predraft:
                    phase_lang = "predraft_phase_info"
                    embed.add_field(name=Lang.lang(self, 'player_database'), value=self.datalink)

                elif self.state == FantasyState.Preseason:
                    phase_lang = "preseason_phase_info"

                elif self.state == FantasyState.Regular:
                    phase_lang = "regular_phase_info"
                    season_str = Lang.lang(self, "curr_week", league.nfl_week, self.year, league.current_week)

                    embed.add_field(name=Lang.lang(self, "curr_season"), value=season_str)

                    overall_str = Lang.lang(self, "overall")
                    division_str = Lang.lang(self, "division")
                    divisions = league.get_divisional_standings()

                    standings_str = ""
                    footer_str = ""
                    if len(divisions) > 1:
                        for div in divisions:
                            standings_str += "{} ({})\n".format(divisions[div][0].team_name, div[0:1])
                            footer_str += "{}: {} {} | ".format(div[0:1], div, division_str)
                    standings_str += "{} ({})".format(league.get_overall_standings()[0].team_name, overall_str[0:1])
                    footer_str += "{}: {}".format(overall_str[0:1], overall_str)

                    embed.add_field(name=Lang.lang(self, "current_leader"), value=standings_str)
                    embed.set_footer(text=footer_str)

                    trade_deadline_int = league.trade_deadline
                    if trade_deadline_int > 0:
                        trade_deadline_str = from_epoch_ms(trade_deadline_int).strftime(Lang.lang(self, "until_strf"))
                        embed.add_field(name=Lang.lang(self, "trade_deadline"), value=trade_deadline_str)

                    activity = league.get_most_recent_activity()
                    if activity is not None:
                        act_str = Lang.lang(self, "last_activity_content",
                                            activity.date.strftime(Lang.lang(self, "until_strf")),
                                            activity.team_name, activity.type, activity.player_name)
                        embed.add_field(name=Lang.lang(self, "last_activity"), value=act_str)

                elif self.state == FantasyState.Postseason:
                    phase_lang = "postseason_phase_info"

                elif self.state == FantasyState.Finished:
                    phase_lang = "finished_phase_info"

                else:
                    await add_reaction(ctx.message, Lang.CMDERROR)
                    await ctx.send(Lang.lang(self, "need_supercommish_leagues"))
                    return

            embed.description = "**{}**\n\n{}".format(Lang.lang(self, phase_lang, date_out_str), self.status)

            await ctx.send(embed=embed)

    @fantasy.command(name="reload", help="Reloads the league data from ESPN")
    async def fantasy_reload(self, ctx):
        async with ctx.typing():
            for league in self.leagues:
                league.reload()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy.group(name="set", help="Set data about the fantasy game.")
    async def fantasy_set(self, ctx):
        is_mod = Config.get(self)['mod_role_id'] != 0 \
                 and Config.get(self)['mod_role_id'] in [role.id for role in ctx.author.roles]
        is_supercomm = self.supercommish is not None and ctx.author.id == self.supercommish.id
        if not permchecks.check_mod_access(ctx.author) and not is_mod and not is_supercomm:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self, "no_set_access"))
            return

        if ctx.invoked_subcommand is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @fantasy_set.command(name="datalink", help="Sets the link for the Players Database")
    async def set_datalink(self, ctx, link):
        link = stringutils.clear_link(link)
        self.datalink = link
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="start", help="Sets the start date of the current fantasy season",
                         usage="DD.MM.[YYYY]")
    async def set_start(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.start_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="end", help="Sets the end date of the current fantasy season",
                         usage="DD.MM.[YYYY]")
    async def set_end(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.end_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="orga", help="Sets the Fantasy Organisator")
    async def set_orga(self, ctx, organisator: Union[discord.Member, discord.User]):
        self.supercommish = organisator
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    # @fantasy_set.command(name="timers", help="Enables or disables the timers to auto-send scores to fantasy channels",
    #                      usage="<on|enable|off|disable>")
    # async def set_timers(self, ctx, arg):
    #     if arg == "on" or arg == "enable":
    #         self.use_timers = True
    #         self._start_score_timer()
    #     elif arg == "off" or arg == "disable":
    #         self.use_timers = False
    #         self._stop_score_timer()
    #     self.save()
    #     await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _save_state(self, ctx, new_state: FantasyState):
        self.state = new_state
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="state", help="Sets the Fantasy state",
                         description="Sets the Fantasy state. "
                                     "Possible states: signup, Predraft, Preseason, Regular, Postseason, Finished",
                         usage="<signup|predraft|preseason|regular|postseason|finished>")
    async def fantasy_set_state(self, ctx, state):
        if state.lower() == "signup":
            await self._save_state(ctx, FantasyState.Sign_up)
        elif state.lower() == "predraft":
            await self._save_state(ctx, FantasyState.Predraft)
        elif state.lower() == "preseason":
            await self._save_state(ctx, FantasyState.Preseason)
        elif state.lower() == "regular":
            await self._save_state(ctx, FantasyState.Regular)
        elif state.lower() == "postseason":
            await self._save_state(ctx, FantasyState.Postseason)
        elif state.lower() == "finished":
            await self._save_state(ctx, FantasyState.Finished)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_phase'))

    @fantasy_set.command(name="date", help="Sets the state end date", usage="DD.MM.[YYYY] [HH:MM]",
                         description="Sets the end date and time for all the phases. "
                                     "If no time is given, 23:59 will be used.")
    async def set_date(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.date = date
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="status", help="Sets the status message",
                         description="Sets a status message for additional information. To remove give no message.")
    async def set_status(self, ctx, *, message):
        self.status = message
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="credentials", help="Sets the ESPN API credentials",
                         description="Sets the ESPN API Credentials based on the credential cookies swid and espn_s2.")
    async def set_api_credentials(self, ctx, swid, espn_s2):
        Storage.get(self)["espn_credentials"]["swid"] = swid
        Storage.get(self)["espn_credentials"]["espn_s2"] = espn_s2
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="config", help="Gets or sets general config values for the plugin")
    async def set_config(self, ctx, key="", value=""):
        if not key and not value:
            await ctx.invoke(self.bot.get_command("configdump"), self.get_name())
            return

        if key and not value:
            key_value = Config.get(self).get(key, None)
            if key_value is None:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'key_not_exists', key))
            else:
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
                await ctx.send(key_value)
            return

        if key == "channel_id":
            channel = None
            int_value = Config.get(self)['channel_id']
            try:
                int_value = int(value)
                channel = self.bot.guild.get_channel(int_value)
            except ValueError:
                pass
            if channel is None:
                Lang.lang(self, 'channel_id')
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = int_value

        elif key == "mod_role_id":
            role = None
            int_value = Config.get(self)['mod_role_id']
            try:
                int_value = int(value)
                role = self.bot.guild.get_role(int_value)
            except ValueError:
                pass
            if role is None:
                Lang.lang(self, 'mod_role_id')
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = int_value

        elif key == "version":
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'version_cant_changed', key))

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="add", help="Adds a new fantasy league",
                         usage="<Sleeper|ESPN> <League ID> [Commissioner Discord user]",
                         description="Adds a new fantasy league hosted on the given platform with the given "
                                     "league ID and the User as commissioner.")
    async def set_add(self, ctx, platform, league_id: int, commish: Union[discord.Member, discord.User, str]):
        platform = platform.lower()
        if platform == "espn" and not Storage.get(self)["espn_credentials"]["espn_s2"] \
                and not Storage.get(self)["espn_credentials"]["swid"]:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "credentials_first", league_id))
            return

        if platform == "espn":
            platform_enum = Platform.ESPN
        elif platform == "sleeper":
            platform_enum = Platform.Sleeper
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "platform_not_supported", platform))
            return

        async with ctx.typing():
            league = FantasyLeague(self, platform_enum, league_id, commish)
        if not league.name:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_add_fail", league_id))
        else:
            self.leagues.append(league)
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            await ctx.send(Lang.lang(self, "league_added", get_best_username(commish), league.name))

    @fantasy_set.command(name="del", help="Removes a fantasy league",
                         usage="<league id> [platform]",
                         description="Removes the fantasy league with the given league ID.")
    async def set_del(self, ctx, league_id: int, platform: Platform = None):
        to_remove = None
        for league in self.leagues:
            if league.league_id != league_id:
                continue

            if platform is not None and league.platform != platform:
                continue

            to_remove = league

        if to_remove is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_id_not_found", league_id))
        else:
            self.leagues.remove(to_remove)
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            await ctx.send(Lang.lang(self, "league_removed", get_best_username(to_remove.commish), to_remove.name))
