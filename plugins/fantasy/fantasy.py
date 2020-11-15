from datetime import datetime, timedelta
from typing import Union, List

import discord
from discord.ext import commands

import botutils.timeutils
from base import BasePlugin, NotFound
from botutils import stringutils, permchecks
from botutils.converters import get_best_username, get_best_user
from botutils.timeutils import from_epoch_ms
from botutils.utils import add_reaction
from conf import Config, Storage, Lang
from plugins.fantasy.league import FantasyLeague, deserialize_league, create_league
from plugins.fantasy.utils import pos_alphabet, FantasyState, Platform, log
from subsystems import timers

# Repo link for pip package for ESPN API https://github.com/cwendt94/espn-api
# Sleeper API doc https://docs.sleeper.app/


class Plugin(BasePlugin, name="NFL Fantasy"):
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
        self.default_league = []
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
            "def_league": None,
            "leagues": [],
            "espn_credentials": {
                "swid": "",
                "espn_s2": ""
            }
        }

    async def shutdown(self):
        self._stop_score_timer()
        self.leagues.clear()

    def command_help_string(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_description(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_desc_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_usage(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_usage_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    @property
    def year(self):
        return self.start_date.year

    def _load(self):
        """Loads the league settings from Storage"""
        if Config.get(self)["version"] == 2:
            self._update_config_from_2_to_3()
        if Config.get(self)["version"] == 3:
            self._update_config_from_3_to_4()
        if Config.get(self)["version"] == 4:
            self._update_config_from_4_to_5()

        self.supercommish = get_best_user(Storage.get(self)["supercommish"])
        self.state = Storage.get(self)["state"]
        self.date = Storage.get(self)["date"]
        self.status = Storage.get(self)["status"]
        self.datalink = Storage.get(self)["datalink"]
        self.start_date = Storage.get(self)["start"]
        self.end_date = Storage.get(self)["end"]
        self.use_timers = Storage.get(self)["timers"]
        self.default_league = Storage.get(self)["def_league"]
        for d in Storage.get(self)["leagues"]:
            self.leagues.append(deserialize_league(self, d))

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
            "def_league": self.default_league,
            "leagues": [el.serialize() for el in self.leagues],
            "espn_credentials": {
                "swid": Storage.get(self)["espn_credentials"]["swid"],
                "espn_s2": Storage.get(self)["espn_credentials"]["espn_s2"]
            }
        }
        Storage.set(self, storage_d)
        Storage.save(self)
        Config.save(self)

    def _update_config_from_4_to_5(self):
        log.info("Updating config from version 4 to version 5")

        Storage.get(self)["def_league"] = []

        Config.get(self)["version"] = 5
        Storage.save(self)
        Config.save(self)

        log.info("Update finished")

    def _update_config_from_3_to_4(self):
        log.info("Updating config from version 3 to version 4")

        for league in Storage.get(self)["leagues"]:
            league['platform'] = Platform.ESPN
            league['league_id'] = league['espn_id']
            del(league['espn_id'])
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

        Config.get(self)["url_base_boxscore"] = self.default_config()["espn"]["url_base_boxscore"]
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

    async def parse_platform(self, platform_name: str = None, ctx=None):
        """
        Parses the given platform string to the Platform enum type

        :param platform_name: The platform name
        :param ctx: returns a message if platform is not supported to the given context
        :return: the Platform enum type or None if not supported
        """
        if platform_name is None:
            return None
        if platform_name.lower() == "espn":
            return Platform.ESPN
        if platform_name.lower() == "sleeper":
            return Platform.Sleeper

        if ctx is not None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "platform_not_supported", platform_name))
        return None

    @commands.group(name="fantasy")
    async def fantasy(self, ctx):
        if Config.get(self)['channel_id'] != 0 and Config.get(self)['channel_id'] != ctx.channel.id:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            raise commands.CheckFailure()

        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('fantasy info'))

    @fantasy.command(name="scores", aliases=["score", "matchup", "matchups", "boxscore", "boxscores"])
    async def scores(self, ctx, *args):
        week = 0
        team_name = None
        league_name = None
        for league in self.leagues:
            try:
                if args[-1].lower() in league.name.lower():
                    league_name = league.name
                    break
            except IndexError:
                break

        try:
            week = int(args[0])
            if len(args) > 1:
                if league_name is None:
                    team_name = " ".join(args[1:])
                else:
                    team_name = " ".join(args[1:-1])
        except (IndexError, ValueError):
            if len(args) > 0:
                if league_name is None:
                    team_name = " ".join(args)
                else:
                    team_name = " ".join(args[:-1])

        await self._write_scores(channel=ctx.channel, week=week, team_name=team_name, league_name=league_name)

    async def _score_send_callback(self, job):
        """Callback method for the timer to auto-send current scores to fantasy channel"""
        channel = self.bot.get_channel(Config.get(self)['channel_id'])
        if channel is not None:
            await self._write_scores(channel=channel, show_errors=False, previous_week=job.data)

    async def _write_scores(self, *, channel: discord.TextChannel, week: int = 0, team_name: str = None,
                            show_errors=True, previous_week=False, league_name: str = None):
        """Send the current scores of given week to given channel"""
        if not self.leagues:
            if show_errors:
                await channel.send(Lang.lang(self, "no_leagues"))
            return

        is_team_in_any_league = False
        no_boxscore_data = None
        for league in self.leagues:
            if league_name is not None and league_name.lower() not in league.name.lower():
                continue
            lweek = week
            if week == 0:
                lweek = league.current_week
            if previous_week:
                lweek -= 1
            if lweek < 1:
                lweek = 1

            async with channel.typing():
                if team_name is None or not team_name:
                    if league_name is None and len(self.default_league) == 2 and \
                            (league.league_id != self.default_league[0] or league.platform != self.default_league[1]):
                        continue
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
        if team_name is not None and team_name and not is_team_in_any_league:
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
        proj = 0.0
        for pl in lineup:
            if pl.slot_position.lower() != "BE".lower():
                msg = "{}{}\n".format(msg, Lang.lang(self, "box_data", pl.slot_position, pl.name,
                                                     pl.proTeam, pl.projected_points, pl.points))
                proj += pl.projected_points
        msg = "{}\n{} {}".format(msg, Lang.lang(self, "box_suffix", score), Lang.lang(self, "box_proj_suffix", proj))

        embed.description = msg
        if opp_name is None:
            embed.set_footer(text=Lang.lang(self, "box_footer_bye"))
        else:
            embed.set_footer(text=Lang.lang(self, "box_footer", opp_name, opp_score))
        return embed

    @fantasy.command(name="standings", aliases=["standing"])
    async def standings(self, ctx, league_name=None):
        if not self.leagues:
            await ctx.send(Lang.lang(self, "no_leagues"))
            return

        for league in self.leagues:
            if league_name is None and len(self.default_league) == 2 and\
                    (league.league_id != self.default_league[0] or league.platform != self.default_league[1]):
                continue

            if league_name is not None and league_name.lower() not in league.name.lower():
                continue

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

    @fantasy.command(name="info")
    async def info(self, ctx, league_name=None):
        if self.supercommish is None or not self.leagues:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "need_supercommish_leagues"))
            return

        date_out_str = Lang.lang(self, 'info_date_str', self.date.strftime(Lang.lang(self, "until_strf")))

        for league in self.leagues:
            if league_name is not None and league_name.lower() not in league.name.lower():
                continue
            embed = discord.Embed(title=league.name)
            embed.url = league.league_url

            embed.add_field(name=Lang.lang(self, "supercommish"), value=self.supercommish.mention)
            com = league.commish.mention if league.commish is not None else Lang.lang(self, "unknown")
            embed.add_field(name=Lang.lang(self, "commish"), value=com)

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

    @fantasy.command(name="reload")
    async def fantasy_reload(self, ctx):
        async with ctx.typing():
            for league in self.leagues:
                league.reload()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy.group(name="set")
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

    @fantasy_set.command(name="datalink")
    async def set_datalink(self, ctx, link):
        link = stringutils.clear_link(link)
        self.datalink = link
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="start")
    async def set_start(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.start_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="end")
    async def set_end(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.end_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="orga", aliases=["organisator"])
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

    @fantasy_set.command(name="state", aliases=["phase"])
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

    @fantasy_set.command(name="date")
    async def set_date(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.date = date
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="status")
    async def set_status(self, ctx, *, message):
        self.status = message
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @fantasy_set.command(name="credentials")
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

    @fantasy_set.command(name="default")
    async def set_default(self, ctx, platform_name, league_id: int = None):
        if platform_name.lower() == "del":
            self.default_league = []
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        platform = await self.parse_platform(platform_name, ctx)
        if platform is None:
            return

        for league in self.leagues:
            if league.league_id == league_id and league.platform == platform:
                self.default_league = [league.league_id, league.platform]
                self.save()
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
                break
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_id_not_found", league_id))

    @fantasy_set.command(name="add")
    async def set_add(self, ctx, platform_name, league_id: int,
                      commish: Union[discord.Member, discord.User, str] = None):
        platform = await self.parse_platform(platform_name, ctx)
        if platform is None:
            return

        if platform == Platform.ESPN and not Storage.get(self)["espn_credentials"]["espn_s2"] \
                and not Storage.get(self)["espn_credentials"]["swid"]:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "credentials_first", league_id))
            return

        async with ctx.typing():
            league = create_league(self, platform, league_id, commish)
        if not league.name:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_add_fail", league_id, platform.name))
        else:
            self.leagues.append(league)
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            com = Lang.lang(self, "nobody") if commish is None or not commish else get_best_username(commish)
            await ctx.send(Lang.lang(self, "league_added", get_best_username(com), league.name))

    @fantasy_set.command(name="del")
    async def set_del(self, ctx, league_id: int, platform_name: Platform = None):
        platform = await self.parse_platform(platform_name, ctx)
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
            com = get_best_username(to_remove.commish) if to_remove.commish is not None else Lang.lang(self, "unknown")
            await ctx.send(Lang.lang(self, "league_removed", com, to_remove.name))
