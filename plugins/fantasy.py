from enum import IntEnum
from threading import Thread
from typing import Dict, Optional, Union, List
import logging

import discord
from espn_api.football import League

from datetime import datetime, timedelta
from discord.ext import commands

import botutils.timeutils
from conf import Config, Storage, Lang
from botutils import stringutils, permchecks
from botutils.timeutils import from_epoch_ms
from botutils.utils import add_reaction
from botutils.converters import get_best_username, get_best_user
from Geckarbot import BasePlugin
from subsystems import timers


# Repo link for pip package for ESPN API https://github.com/cwendt94/espn-api


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
            connect_thread = Thread(target=self._connect_espn)
            connect_thread.start()
        else:
            self._connect_espn()

    def _connect_espn(self):
        self.espn = League(year=self.plugin.year, league_id=self.espn_id,
                           espn_s2=Storage.get(self.plugin)["api"]["espn_s2"],
                           swid=Storage.get(self.plugin)["api"]["swid"])
        logging.getLogger("fantasy").info("League {}, ID {} connected".format(self.name, self.espn_id))

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
            'commish': self.commish.id,
        }

    @classmethod
    def deserialize(cls, plugin, d: dict):
        """
        Constructs a FantasyLeague object from a dict.

        :param plugin: The plugin instance
        :param d: dict made by serialize()
        :return: FantasyLeague object
        """
        return FantasyLeague(plugin, d['espn_id'], get_best_user(plugin.bot, d['commish']))


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
        self.end_date = datetime.now() + timedelta(days=16*7)
        self.leagues = {}  # type: Dict[int, FantasyLeague]
        self._score_timer_jobs = []  # type: List[timers.Job]

        self._load()
        self._start_score_timer()

    def default_config(self):
        return {
            "version": 2,
            "channel_id": 0,
            "mod_role_id": 0,
            "url_base_league": "https://fantasy.espn.com/football/league?leagueId=",
            "url_base_scoreboard": "https://fantasy.espn.com/football/league/scoreboard?leagueId=",
            "url_base_standings": "https://fantasy.espn.com/football/league/standings?leagueId="
        }

    def default_storage(self):
        return {
            "supercommish": 0,
            "state": FantasyState.NA,
            "date": datetime.now(),
            "status": "",
            "datalink": None,
            "start": datetime.now(),
            "end": datetime.now() + timedelta(days=16*7),
            "leagues": [],
            "api": {
                "swid": "",
                "espn_s2": ""
            }
        }

    @property
    def year(self):
        return self.start_date.year

    def _load(self):
        """Loads the league settings from Storage"""
        self.supercommish = get_best_user(self.bot, Storage.get(self)["supercommish"])
        self.state = Storage.get(self)["state"]
        self.date = Storage.get(self)["date"]
        self.status = Storage.get(self)["status"]
        self.datalink = Storage.get(self)["datalink"]
        self.start_date = Storage.get(self)["start"]
        self.end_date = Storage.get(self)["end"]
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
            "leagues": [el.serialize() for el in self.leagues.values()],
            "api": {
                "swid": Storage.get(self)["api"]["swid"],
                "espn_s2": Storage.get(self)["api"]["espn_s2"]
            }
        }
        Storage.set(self, storage_d)
        Storage.save(self)
        Config.save(self)

    def _start_score_timer(self):
        """
        Starts the timer for auto-send scores to channel.
        If timer is already started, timer will be cancelled and removed before restart.
        Timer will be started only if Config().DEBUG_MODE is False.
        """
        if Config().DEBUG_MODE:
            logging.getLogger("fantasy").warning("DEBUG MODE is on, fantasy timers will not be started!")
            return

        for timer in self._score_timer_jobs:
            if not timer.cancelled:
                timer.cancel()

        year_range = list(range(self.start_date.year, self.end_date.year + 1))
        month_range = list(range(self.start_date.month, self.end_date.month + 1))
        timedict_12h = timers.timedict(year=year_range, month=month_range, weekday=[1, 2, 5], hour=12, minute=0)
        timedict_sun = timers.timedict(year=year_range, month=month_range, weekday=7, hour=[18, 22], minute=45)
        timedict_mon = timers.timedict(year=year_range, month=month_range, weekday=1, hour=1, minute=45)
        self._score_timer_jobs = [
            self.bot.timers.schedule(self._score_send_callback, timedict_12h, repeat=True),
            self.bot.timers.schedule(self._score_send_callback, timedict_sun, repeat=True),
            self.bot.timers.schedule(self._score_send_callback, timedict_mon, repeat=True)
        ]

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

    @fantasy.command(name="scores", help="Gets the matchup scores")
    async def scores(self, ctx, week: int = 0):
        async with ctx.typing():
            await self._send_scores(ctx.channel, week)

    async def _score_send_callback(self, job):
        """Callback method for the timer to auto-send current scores to fantasy channel"""
        channel = self.bot.get_channel(Config.get(self)['channel_id'])
        if channel is not None:
            await self._send_scores(channel)

    async def _send_scores(self, channel: discord.TextChannel, week: int = 0, show_errors=True):
        """Send the current scores of given week to given channel"""
        if not self.leagues:
            if show_errors:
                await channel.send(Lang.lang(self, "no_leagues"))
            return

        for league in self.leagues.values():
            week = week if 0 < week <= league.espn.current_week else league.espn.current_week
            prefix = Lang.lang(self, "scores_prefix", league.name, week)
            embed = discord.Embed(title=prefix, url=league.scoreboard_url)

            match_no = 0
            bye_team = None
            for match in league.espn.box_scores(week):
                if match.home_team is None or match.home_team == 0:
                    bye_team = match.away_team.team_name
                    continue
                elif match.away_team is None or match.away_team == 0:
                    bye_team = match.home_team.team_name
                    continue
                match_no += 1
                name_str = Lang.lang(self, "matchup_name", match_no)
                value_str = Lang.lang(self, "matchup_data", match.away_team.team_name, match.away_score,
                                      match.home_team.team_name, match.home_score)
                embed.add_field(name=name_str, value=value_str)

            if bye_team is not None:
                embed.add_field(name=Lang.lang(self, "on_bye"), value=bye_team)

            await channel.send(embed=embed)

    @fantasy.command(name="standings", help="Gets the full current standings")
    async def standings(self, ctx):
        # TODO after week 1
        for league in self.leagues.values():
            embed = discord.Embed(title=league.name)
            embed.url = league.scoreboard_url

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
                standings = league.espn.standings()

                embed.add_field(name=Lang.lang(self, "curr_season"), value=season_str)
                # TODO better standings, East, West, Overall
                embed.add_field(name=Lang.lang(self, "current_leader"), value=standings[0].team_name)

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

    @fantasy.group(name="set", help="Set data about the fantasy game.")
    async def fantasy_set(self, ctx):
        is_mod = Config.get(self)['mod_role_id'] != 0 \
                 and Config.get(self)['mod_role_id'] in [role.id for role in ctx.author.roles]
        is_supercomm = self.supercommish is not None and ctx.author.id == self.supercommish.id
        if not permchecks.check_full_access(ctx.author) and not is_mod and not is_supercomm:
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
