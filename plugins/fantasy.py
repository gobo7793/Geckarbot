import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from enum import IntEnum
from threading import Thread
from typing import Dict, Optional, Union, List

import discord
from discord.ext import commands
from espn_api.football import League, Team

import botutils.timeutils
from base import BasePlugin
from botutils import stringutils, permchecks
from botutils.converters import get_best_username, get_best_user
from botutils.timeutils import from_epoch_ms
from botutils.utils import add_reaction
from conf import Config, Storage, Lang
from subsystems import timers

# Repo link for pip package for ESPN API https://github.com/cwendt94/espn-api


log = logging.getLogger("fantasy")
pos_alphabet = {"Q": 0, "R": 1, "W": 2, "T": 3, "F": 4, "D": 5, "K": 6, "B": 7}


class FantasyState(IntEnum):
    """Fantasy states"""
    NA = 0
    Sign_up = 1
    Predraft = 2
    Preseason = 3
    Regular = 4
    Postseason = 5
    Finished = 6


class FantasyLeague:
    """Fatasy Football League dataset"""

    def __init__(self, plugin, espn_id: int, commish: discord.User, init=False):
        """
        Creates a new FantasyLeague dataset instance

        :param plugin: The fantasy plugin instance
        :param espn_id: The ESPN league ID
        :param commish: The commissioner
        :param init: True if league is loading from Storage
        """
        self.plugin = plugin
        self.espn_id = espn_id
        self.commish = commish
        self.espn = None  # type: Optional[League]

        if init:
            connect_thread = Thread(target=self.load_espn_data)
            connect_thread.start()
        else:
            self.load_espn_data()

    def load_espn_data(self):
        self.espn = League(year=self.plugin.year, league_id=self.espn_id,
                           espn_s2=Storage.get(self.plugin)["api"]["espn_s2"],
                           swid=Storage.get(self.plugin)["api"]["swid"])
        log.info("League {}, ID {} connected".format(self.name, self.espn_id))

    def __str__(self):
        return "<fantasy.FantasyLeague; espn_id: {}, commish: {}, espn: {}>".format(
            self.espn_id, self.commish, self.espn)

    @property
    def name(self):
        if self.espn is not None:
            return self.espn.settings.name
        return ""

    @property
    def year(self):
        if self.espn is not None:
            return self.espn.year
        return self.plugin.year

    @property
    def league_url(self):
        return "{}{}".format(Config.get(self.plugin)["url_base_league"], self.espn_id)

    @property
    def scoreboard_url(self):
        return "{}{}".format(Config.get(self.plugin)["url_base_scoreboard"], self.espn_id)

    @property
    def standings_url(self):
        return "{}{}".format(Config.get(self.plugin)["url_base_standings"], self.espn_id)

    def serialize(self):
        """
        Serializes the league dataset to a dict

        :return: A dict with the espn_id and commish
        """
        return {
            'espn_id': self.espn_id,
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
        return FantasyLeague(plugin, d['espn_id'], get_best_user(d['commish']))


def _get_division_standings(league: FantasyLeague):
    """Returns a dict with key division_name and value a sorted list with the current division standing"""
    divisions = {}
    for team in league.espn.standings():
        if team.division_name not in divisions:
            divisions[team.division_name] = []
        divisions[team.division_name].append(team)

    return OrderedDict(sorted(divisions.items()))


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
        self.leagues = {}  # type: Dict[int, FantasyLeague]
        self._score_timer_jobs = []  # type: List[timers.Job]

        self._load()
        self._start_score_timer()

    def default_config(self):
        return {
            "version": 3,
            "channel_id": 0,
            "mod_role_id": 0,
            "url_base_league": "https://fantasy.espn.com/football/league?leagueId=",
            "url_base_scoreboard": "https://fantasy.espn.com/football/league/scoreboard?leagueId=",
            "url_base_standings": "https://fantasy.espn.com/football/league/standings?leagueId=",
            "url_base_boxscore":
                "https://fantasy.espn.com/football/boxscore?leagueId={}&matchupPeriodId={}&seasonId={}&teamId={}"
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
            "api": {
                "swid": "",
                "espn_s2": ""
            }
        }

    async def shutdown(self):
        self._stop_score_timer()

    @property
    def year(self):
        return self.start_date.year

    def get_boxscore_link(self, league: FantasyLeague, week, teamid):
        return Config.get(self)["url_base_boxscore"].format(league.espn_id, week, league.year, teamid)

    def _load(self):
        """Loads the league settings from Storage"""
        if Config.get(self)["version"] == 2:
            self._update_config_from_2_to_3()

        self.supercommish = get_best_user(Storage.get(self)["supercommish"])
        self.state = Storage.get(self)["state"]
        self.date = Storage.get(self)["date"]
        self.status = Storage.get(self)["status"]
        self.datalink = Storage.get(self)["datalink"]
        self.start_date = Storage.get(self)["start"]
        self.end_date = Storage.get(self)["end"]
        self.use_timers = Storage.get(self)["timers"]
        for d in Storage.get(self)["leagues"]:
            self.leagues[d["espn_id"]] = FantasyLeague.deserialize(self, d)

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
            "leagues": [el.serialize() for el in self.leagues.values()],
            "api": {
                "swid": Storage.get(self)["api"]["swid"],
                "espn_s2": Storage.get(self)["api"]["espn_s2"]
            }
        }
        Storage.set(self, storage_d)
        Storage.save(self)
        Config.save(self)

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

        async with ctx.typing():
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
        for league in self.leagues.values():
            lweek = week
            if week == 0:
                lweek = league.espn.current_week
            if previous_week:
                lweek -= 1
            if lweek < 1:
                lweek = 1

            if team_name is None:
                embed = self._get_league_score_embed(league, lweek)
            else:
                team = next((t for t in league.espn.teams
                             if team_name.lower() in t.team_name.lower()
                             or t.team_abbrev.lower() == team_name.lower()), None)
                if team is None:
                    continue
                embed = self._get_boxscore_embed(league, team, lweek)
                is_team_in_any_league = True

            if embed is not None:
                await channel.send(embed=embed)

        if team_name is not None and not is_team_in_any_league:
            await channel.send(Lang.lang(self, "team_not_found", team_name))

    def _get_league_score_embed(self, league: FantasyLeague, week: int):
        """Builds the discord.Embed for scoring overview in league with all matches"""
        prefix = Lang.lang(self, "scores_prefix", league.name,
                           week if week <= league.espn.current_week else league.espn.current_week)
        embed = discord.Embed(title=prefix, url=league.scoreboard_url)

        match_no = 0
        bye_team = None
        bye_pts = 0
        for match in league.espn.box_scores(week):
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

    def _get_boxscore_embed(self, league: FantasyLeague, team: Team, week: int):
        """Builds the discord.Embed for the boxscore for given team in given week"""
        match = next((b for b in league.espn.box_scores(week) if b.home_team == team or b.away_team == team), None)
        if match is None:
            return

        opp_name = None
        opp_score = None
        if match.home_team == team:
            score = match.home_score
            lineup = match.home_lineup
            opp_name = None
            if match.away_team != 0:
                opp_name = match.away_team.team_name
                opp_score = match.away_score
        else:
            score = match.away_score
            lineup = match.away_lineup
            if match.home_team != 0:
                opp_name = match.home_team.team_name
                opp_score = match.home_score

        for pl in lineup:
            if "RB/WR".lower() in pl.slot_position.lower():
                pl.slot_position = "FLEX"
        lineup = sorted(lineup, key=lambda word: [pos_alphabet.get(c, ord(c)) for c in word.slot_position])

        prefix = Lang.lang(self, "box_prefix", team.team_name, league.name, week)
        embed = discord.Embed(title=prefix, url=self.get_boxscore_link(league, week, team.team_id))

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

        for league in self.leagues.values():
            embed = discord.Embed(title=league.name)
            embed.url = league.standings_url

            divisions = _get_division_standings(league)
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

        for league in self.leagues.values():
            embed = discord.Embed(title=league.name)
            embed.url = league.league_url

            embed.add_field(name=Lang.lang(self, "supercommish"), value=self.supercommish.mention)
            embed.add_field(name=Lang.lang(self, "commish"), value=league.commish.mention)

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
                season_str = Lang.lang(self, "curr_week", league.espn.nfl_week, self.year, league.espn.current_week)

                embed.add_field(name=Lang.lang(self, "curr_season"), value=season_str)

                overall_str = Lang.lang(self, "overall")
                division_str = Lang.lang(self, "division")
                standings = league.espn.standings()
                divisions = _get_division_standings(league)

                standings_str = ""
                footer_str = ""
                for div in divisions:
                    standings_str += "{} ({})\n".format(divisions[div][0].team_name, div[0:1])
                    footer_str += "{}: {} {} | ".format(div[0:1], div, division_str)
                standings_str += "{} ({})".format(standings[0].team_name, overall_str[0:1])
                footer_str += "{}: {}".format(overall_str[0:1], overall_str)

                embed.add_field(name=Lang.lang(self, "current_leader"), value=standings_str)
                embed.set_footer(text=footer_str)

                trade_deadline_int = league.espn.settings.trade_deadline
                if trade_deadline_int > 0:
                    trade_deadline_str = from_epoch_ms(trade_deadline_int).strftime(Lang.lang(self, "until_strf"))
                    embed.add_field(name=Lang.lang(self, "trade_deadline"), value=trade_deadline_str)

                activities = league.espn.recent_activity()
                if activities:
                    act_date = from_epoch_ms(activities[0].date).strftime(Lang.lang(self, "until_strf"))
                    act_team = activities[0].actions[0][0].team_name
                    act_type = activities[0].actions[0][1]
                    act_player = activities[0].actions[0][2]
                    act_str = Lang.lang(self, "last_activity_content", act_date, act_team, act_type, act_player)
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
            for league in self.leagues.values():
                league.espn.refresh()
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
        Storage.get(self)["api"]["swid"] = swid
        Storage.get(self)["api"]["espn_s2"] = espn_s2
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
                         usage="<ESPN League ID> <Commissioner Discord user>",
                         description="Adds a new fantasy league with the given "
                                     "ESPN league ID and the User as commissioner.")
    async def set_add(self, ctx, espn_id: int, commish: Union[discord.Member, discord.User]):
        if not Storage.get(self)["api"]["espn_s2"] and not Storage.get(self)["api"]["swid"]:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "credentials_first", espn_id))
            return

        async with ctx.typing():
            league = FantasyLeague(self, espn_id, commish)
            if league.espn is None:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "league_add_fail", espn_id))
            else:
                self.leagues[espn_id] = league
                self.save()
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
                await ctx.send(Lang.lang(self, "league_added", get_best_username(commish), league.name))

    @fantasy_set.command(name="del", help="Removes a fantasy league",
                         description="Removes the fantasy league with the given ESPN league ID.")
    async def set_del(self, ctx, espn_id: int):
        if espn_id not in self.leagues:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_id_not_found", espn_id))
            return

        league = self.leagues[espn_id]
        del (self.leagues[espn_id])
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send(Lang.lang(self, "league_removed", get_best_username(league.commish), league.name))
