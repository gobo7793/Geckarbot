import logging
from datetime import datetime, timedelta
from typing import Union, List, Dict, Optional

from nextcord import TextChannel, Embed, Member, User
from nextcord.ext import commands
from nextcord.ext.commands import TextChannelConverter, ChannelNotFound, RoleConverter, RoleNotFound, Context

import botutils.timeutils
from base.configurable import BasePlugin
from base.data import Config, Storage, Lang
from botutils import stringutils, permchecks
from botutils.converters import get_best_username, get_best_user
from botutils.permchecks import WrongChannel
from botutils.stringutils import paginate
from botutils.utils import add_reaction, helpstring_helper, execute_anything_sync
from plugins.fantasy import migrations
from plugins.fantasy.league import FantasyLeague, deserialize_league, create_league
from plugins.fantasy.utils import pos_alphabet, FantasyState, Platform, Match, parse_platform
from services import timers
from services.helpsys import DefaultCategories

log = logging.getLogger(__name__)


# Repo link for pip package for ESPN API https://github.com/cwendt94/espn-api
# Sleeper API doc https://docs.sleeper.app/


class Plugin(BasePlugin, name="NFL Fantasy"):
    """Commands for the Fantasy game"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category=DefaultCategories.SPORT)
        self.dump_except_keys = ["espn_credentials"]

        self.supercommish = None
        self.state = FantasyState.NA
        self.date = datetime.now()
        self.status = ""
        self.datalink = None
        self.start_date = datetime.now()
        self.end_date = datetime.now() + timedelta(days=16 * 7)
        self.use_timers = False
        self.default_league = -1
        self.leagues = {}  # type: Dict[int, FantasyLeague]
        self._score_timer_jobs = []  # type: List[timers.Job]

        execute_anything_sync(self._load())
        # self._load()
        # self._start_score_timer()

    def default_config(self, container=None):
        return {
            "version": 7,
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
            },
            "espn_credentials": {
                "swid": "",
                "espn_s2": ""
            }
        }

    def default_storage(self, container=None):
        if container is None:
            return {
                "supercommish": 0,
                "state": FantasyState.NA,
                "date": datetime.now(),
                "status": "",
                "datalink": None,
                "start": datetime.now(),
                "end": datetime.now() + timedelta(days=16 * 7),
                "timers": False,
                "def_league": -1,
                "leagues": []
            }
        return {}

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    async def shutdown(self):
        self._stop_score_timer()
        self.leagues.clear()

    @property
    def year(self):
        return self.start_date.year

    async def _load(self):
        """Loads the league settings from Storage"""
        migrations.migrate(self)

        self.supercommish = get_best_user(Storage.get(self)["supercommish"])
        self.state = Storage.get(self)["state"]
        self.date = Storage.get(self)["date"]
        self.status = Storage.get(self)["status"]
        self.datalink = Storage.get(self)["datalink"]
        self.start_date = Storage.get(self)["start"]
        self.end_date = Storage.get(self)["end"]
        self.use_timers = Storage.get(self)["timers"]
        self.default_league = Storage.get(self)["def_league"]
        for k in Storage.get(self)["leagues"]:
            self.leagues[k] = await deserialize_league(self, Storage.get(self)["leagues"][k])

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
            "leagues": {k: el.serialize() for k, el in self.leagues.items()}
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

    async def parse_platform(self, platform_name: str = None, ctx: Context = None) -> Optional[Platform]:
        """
        Parses the given platform string to the Platform enum type
        and writes a error message if platform is not supported

        :param platform_name: The platform name
        :param ctx: returns a message if platform is not supported to the given context
        :return: the Platform enum type or None if not supported
        """
        platform = parse_platform(platform_name)
        if platform is not None:
            return platform

        if ctx is not None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "platform_not_supported", platform_name))
        return None

    def can_skip_league(self, league_key: int, league_name: str = None):
        """Decides if the league can be ignored cause of the league name or it's not the default league"""
        if league_name is None and self.default_league > -1 and self.default_league != league_key:
            return True
        if league_name is not None and league_name:
            if league_name.lower() == "all":
                return False
            if league_name.lower() not in self.leagues[league_key].name.lower():
                return True
        return False

    @commands.group(name="fantasy")
    async def cmd_fantasy(self, ctx):
        if Config.get(self)['channel_id'] != 0 and Config.get(self)['channel_id'] != ctx.channel.id:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            raise WrongChannel(Config.get(self)['channel_id'])

        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('fantasy info'))

    @cmd_fantasy.command(name="scores", aliases=["score", "matchup", "matchups", "boxscore", "boxscores"])
    async def cmd_scores(self, ctx, *args):
        # Base cmd syntax: !fantasy scores week team_name... league_name
        week = 0
        team_name = None
        league_name = None

        # handle if week isn't first arg
        if len(args) > 1:
            try:
                week = int(args[0])
                week_first = True
            except ValueError:
                week_first = False

            week_not_first = False
            for arg in args[1:]:
                try:
                    int(arg)
                    week_not_first = True
                    break
                except ValueError:
                    week_not_first = False
            if not week_first and week_not_first:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.channel.send(Lang.lang(self, "week_must_first"))
                return

        # league name
        for league in self.leagues.values():
            try:
                if args[-1].lower() == "all":
                    league_name = "all"
                elif args[-1].lower() in league.name.lower():
                    league_name = league.name
                    break
            except IndexError:
                break

        # week and team name
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

    async def _write_scores(self, *, channel: TextChannel, week: int = 0, team_name: str = None,
                            show_errors=True, previous_week=False, league_name: str = None):
        """Send the current scores of given week to given channel"""
        if not self.leagues:
            if show_errors:
                await channel.send(Lang.lang(self, "no_leagues"))
            return

        results = []
        async with channel.typing():
            if self.default_league > -1 and (league_name is None or not league_name):
                res = await self._write_scores_league_perform(self.leagues[self.default_league], week,
                                                              previous_week, team_name)
                if res is not None:
                    results.append(res)

            if not results:
                for k, el in self.leagues.items():
                    if league_name is not None and league_name.lower() != "all" and \
                            (k == self.default_league or
                             (league_name is not None and league_name
                              and league_name.lower() != el.name.lower())):
                        # default league already done directly above
                        continue

                    res = await self._write_scores_league_perform(el, week,
                                                                  previous_week, team_name)
                    if res is not None:
                        results.append(res)

        if not results:
            # there's always a result for league scores, so only for boxscore
            await channel.send(Lang.lang(self, "team_not_found", team_name))

        for result in results:
            if isinstance(result, Embed):
                await channel.send(embed=result)
            if isinstance(result, str):
                await channel.send(result)

    async def _write_scores_league_perform(self, league: FantasyLeague, week: int,
                                           previous_week: bool, team_name: str = None) \
            -> Union[Embed, str, None]:
        """
        Decides which league data should be outputed, league scores or boxscores for given team_name

        :return: The Embed to output (always the case for league scores),
                 None if no output possible based on input data,
                 or a Tuple(team_name, platform, boxscore_url) if platform doesn't support API boxscores.
        """
        lweek = week
        if week == 0:
            lweek = league.current_week
        if previous_week:
            lweek -= 1
        lweek = max(lweek, 1)

        try:
            # full league score
            if team_name is None or not team_name:
                return await self._get_league_score_embed(league, lweek)

            # boxscore of both teams
            if len(team_name) > 1 and team_name.startswith("#"):
                try:
                    match_id = int(team_name[1:]) - 1
                except (IndexError, ValueError):
                    return Lang.lang(self, "wrong_match_id")

                match = next(iter(await league.get_boxscores(lweek, match_id)), None)
                if match is None:
                    return Lang.lang(self, "wrong_match_id")
                embed_away = await self._get_boxscore_embed(league, lweek, team=match.away_team, match=match)
                embed_home = await self._get_boxscore_embed(league, lweek, team=match.home_team, match=match)
                full_embed = Embed(title=Lang.lang(self, "match_boxscore", match_id + 1, league.name, lweek),
                                           url=embed_away.url)
                full_embed.add_field(name=match.away_team.team_name, value=embed_away.description, inline=False)
                full_embed.add_field(name=match.home_team.team_name, value=embed_home.description, inline=False)
                return full_embed

            # single team boxscore
            team = next((t for t in league.get_teams()
                         if team_name.lower() in t.team_name.lower()
                         or t.team_abbrev.lower() == team_name.lower()), None)
            if team is None:
                return
            if league.platform == Platform.SLEEPER:
                return Lang.lang(self, "no_boxscore_data", team.team_name, league.platform,
                                 league.get_boxscore_url(week, team.team_id))
            return await self._get_boxscore_embed(league, lweek, team=team)

        except (IndexError, ValueError):
            return Lang.lang(self, "api_error", league.name)

    async def _get_league_score_embed(self, league: FantasyLeague, week: int):
        """Builds the discord.Embed for scoring overview in league with all matches"""
        prefix = Lang.lang(self, "scores_prefix", league.name,
                           week if week <= league.current_week else league.current_week)
        embed = Embed(title=prefix, url=league.scoreboard_url)

        match_no = 0
        bye_team = None
        bye_pts = 0
        for match in await league.get_boxscores(week):
            if match.home_team is None or match.home_team == 0 or not match.home_team:
                bye_team = match.away_team.team_name
                bye_pts = match.away_score
                continue
            if match.away_team is None or match.away_team == 0 or not match.away_team:
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

    async def _get_boxscore_embed(self, league: FantasyLeague, week: int, team=None, match: Match = None):
        """Builds the discord.Embed for the boxscore for given team in given week"""
        if match is None:
            # first search match based on team name if match isn't given before aborting
            match = next((b for b in await league.get_boxscores(week)
                          if (b.home_team is not None and b.home_team.team_name.lower() == team.team_name.lower())
                          or (b.away_team is not None and b.away_team.team_name.lower() == team.team_name.lower())),
                         None)
        if match is None:
            return

        opp_name = None
        opp_score = None
        opp_lineup = None
        if match.home_team == team:
            score = match.home_score
            lineup = match.home_lineup
            opp_name = None
            if match.away_team is not None:
                opp_name = match.away_team.team_name
                opp_score = match.away_score
                opp_lineup = match.away_lineup
        else:
            score = match.away_score
            lineup = match.away_lineup
            if match.home_team is not None:
                opp_name = match.home_team.team_name
                opp_score = match.home_score
                opp_lineup = match.home_lineup

        lineup = sorted(lineup, key=lambda word: [pos_alphabet.get(c, ord(c)) for c in word.slot_position])

        prefix = Lang.lang(self, "box_prefix", team.team_name, league.name, week)
        embed = Embed(title=prefix, url=league.get_boxscore_url(week, team.team_id))

        msg = ""
        proj = 0.0
        for pl in lineup:
            if pl.slot_position.lower() != "BE".lower():
                points = str(pl.points)
                if isinstance(pl.points, int):
                    points = "-"
                msg = "{}{}\n".format(msg, Lang.lang(self, "box_data", pl.slot_position, pl.name,
                                                     pl.proTeam, pl.projected_points, points))
                proj += pl.projected_points
        msg = "{}\n{}".format(msg, Lang.lang(self, "box_suffix", score, proj))

        embed.description = msg
        if opp_name is None:
            embed.set_footer(text=Lang.lang(self, "box_footer_bye"))
        else:
            opp_proj = 0.0
            for pl in opp_lineup:
                opp_proj += pl.projected_points
            embed.set_footer(text=Lang.lang(self, "box_footer", opp_name, opp_score, opp_proj))
        return embed

    @cmd_fantasy.command(name="standings", aliases=["standing"])
    async def cmd_standings(self, ctx, league_name=None):
        if not self.leagues:
            await ctx.send(Lang.lang(self, "no_leagues"))
            return

        for k, el in self.leagues.items():
            try:
                if self.can_skip_league(k, league_name):
                    continue

                league = el
                embed = Embed(title=league.name)
                embed.url = league.standings_url

                async with ctx.typing():
                    divisions = await league.get_divisional_standings()
                    for division in divisions:
                        div = divisions[division]
                        standing_str = "\n".join([
                            Lang.lang(self, "standings_data", t + 1, div[t].team_name, div[t].wins, div[t].losses)
                            for t in range(len(div))])
                        embed.add_field(name=division, value=standing_str)

                await ctx.send(embed=embed)

            except (IndexError, ValueError):
                await ctx.send(Lang.lang(self, "api_error", el.name))

    @cmd_fantasy.command(name="info")
    async def cmd_info(self, ctx, league_name=None):
        if self.supercommish is None or not self.leagues:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "need_supercommish_leagues"))
            return

        date_out_str = Lang.lang(self, 'info_date_str', self.date.strftime(Lang.lang(self, "until_strf")))

        for k, el in self.leagues.items():
            if self.can_skip_league(k, league_name):
                continue

            league = el
            embed = Embed(title=league.name)
            embed.url = league.league_url

            embed.add_field(name=Lang.lang(self, "supercommish"), value=self.supercommish.mention)
            com = league.commish.mention if league.commish is not None else Lang.lang(self, "unknown")
            embed.add_field(name=Lang.lang(self, "commish"), value=com)

            async with ctx.typing():
                if self.state == FantasyState.SIGN_UP:
                    phase_lang = "signup_phase_info"
                    date_out_str = date_out_str if self.date > datetime.now() else ""
                    embed.add_field(name=Lang.lang(self, 'sign_up_at'), value=self.supercommish.mention)

                elif self.state == FantasyState.PREDRAFT:
                    phase_lang = "predraft_phase_info"
                    embed.add_field(name=Lang.lang(self, 'player_database'), value=self.datalink)

                elif self.state == FantasyState.PRESEASON:
                    phase_lang = "preseason_phase_info"

                elif self.state == FantasyState.REGULAR:
                    has_api_errors = False
                    phase_lang = "regular_phase_info"
                    season_str = Lang.lang(self, "curr_week", league.nfl_week, self.year, league.current_week)

                    embed.add_field(name=Lang.lang(self, "curr_season"), value=season_str)

                    overall_str = Lang.lang(self, "overall")
                    division_str = Lang.lang(self, "division")
                    footer_str = ""
                    try:
                        divisions = await league.get_divisional_standings()

                        standings_str = ""
                        if len(divisions) > 1:
                            for div in divisions:
                                standings_str += "{} ({})\n".format(divisions[div][0].team_name, div[0:1])
                                footer_str += "{}: {} {} | ".format(div[0:1], div, division_str)
                        standings = await league.get_overall_standings()
                        standings_str += "{} ({})".format(standings[0].team_name,
                                                          overall_str[0:1])
                        footer_str += "{}: {}".format(overall_str[0:1], overall_str)

                        embed.add_field(name=Lang.lang(self, "current_leader"), value=standings_str)
                    except (ValueError, IndexError):
                        has_api_errors = True

                    embed.add_field(name=Lang.lang(self, "trade_deadline"), value=league.trade_deadline)

                    try:
                        activity = await league.get_most_recent_activity()
                        if activity is not None:
                            act_str = Lang.lang(self, "last_activity_content",
                                                activity.date.strftime(Lang.lang(self, "until_strf")),
                                                activity.team_name, activity.type, activity.player_name)
                            embed.add_field(name=Lang.lang(self, "last_activity"), value=act_str)
                    except (ValueError, IndexError):
                        has_api_errors = True

                    if has_api_errors:
                        footer_str = " | ".join([footer_str, Lang.lang(self, "api_error_short")])
                    embed.set_footer(text=footer_str)

                elif self.state == FantasyState.POSTSEASON:
                    phase_lang = "postseason_phase_info"

                elif self.state == FantasyState.FINISHED:
                    phase_lang = "finished_phase_info"

                else:
                    await add_reaction(ctx.message, Lang.CMDERROR)
                    await ctx.send(Lang.lang(self, "need_supercommish_leagues"))
                    return

            embed.description = "**{}**\n\n{}".format(Lang.lang(self, phase_lang, date_out_str), self.status)

            await ctx.send(embed=embed)

    @cmd_fantasy.command(name="reload")
    async def cmd_fantasy_reload(self, ctx):
        has_errors = False
        async with ctx.typing():
            for league in self.leagues.values():
                try:
                    await league.reload()
                except (ValueError, IndexError):
                    has_errors = True
                    ctx.send(Lang.lang(self, "api_error", league.name))
        if has_errors:
            await add_reaction(ctx.message, Lang.CMDERROR)
        else:
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy.group(name="set")
    async def cmd_fantasy_set(self, ctx):
        def check_mod_perms():
            if permchecks.check_mod_access(ctx.author):
                return True
            # if Config.get(self)['mod_role_id'] == 0:
            #     return False
            if Config.get(self)['mod_role_id'] in [role.id for role in ctx.author.roles]:
                return True
            return False

        def check_supercommish():
            if self.supercommish is None:
                return True
            if ctx.author.id == self.supercommish.id:
                return True
            return False

        if not (check_supercommish() or check_mod_perms()):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            raise commands.CheckFailure(message=Lang.lang(self, "no_set_access"))

        if ctx.invoked_subcommand is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd_fantasy_set.command(name="datalink")
    async def cmd_set_datalink(self, ctx, link):
        link = stringutils.clear_link(link)
        self.datalink = link
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="start")
    async def cmd_set_start(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.start_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="end")
    async def cmd_set_end(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.end_date = date
        self.save()
        self._start_score_timer()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="orga", aliases=["organisator"])
    async def cmd_set_orga(self, ctx, organisator: Union[Member, User]):
        self.supercommish = organisator
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    # @cmd_fantasy_set.command(name="timers",
    # help="Enables or disables the timers to auto-send scores to fantasy channels",
    #                      usage="<on|enable|off|disable>")
    # async def cmd_set_timers(self, ctx, arg):
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

    @cmd_fantasy_set.command(name="state", aliases=["phase"])
    async def cmd_fantasy_set_state(self, ctx, state):
        if state.lower() == "signup":
            await self._save_state(ctx, FantasyState.SIGN_UP)
        elif state.lower() == "predraft":
            await self._save_state(ctx, FantasyState.PREDRAFT)
        elif state.lower() == "preseason":
            await self._save_state(ctx, FantasyState.PRESEASON)
        elif state.lower() == "regular":
            await self._save_state(ctx, FantasyState.REGULAR)
        elif state.lower() == "postseason":
            await self._save_state(ctx, FantasyState.POSTSEASON)
        elif state.lower() == "finished":
            await self._save_state(ctx, FantasyState.FINISHED)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_phase'))

    @cmd_fantasy_set.command(name="date")
    async def cmd_set_date(self, ctx, *args):
        date = botutils.timeutils.parse_time_input(args, end_of_day=True)
        self.date = date
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="status")
    async def cmd_set_status(self, ctx, *, message):
        self.status = message
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="credentials")
    async def cmd_set_api_credentials(self, ctx, swid, espn_s2):
        Config.get(self)["espn_credentials"]["swid"] = swid
        Config.get(self)["espn_credentials"]["espn_s2"] = espn_s2
        self.save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="config", help="Gets or sets general config values for the plugin")
    async def cmd_set_config(self, ctx, key="", value=""):
        if not key and not value:
            msg = []
            for k in Config.get(self):
                if k != "espn_credentials":
                    msg.append("{}: {}".format(k, Config.get(self)[k]))
            for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
                await ctx.send(msg)
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
            try:
                channel = await TextChannelConverter().convert(ctx, value)
            except ChannelNotFound:
                channel = None

            if channel is None:
                Lang.lang(self, 'channel_id')
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
            Config.get(self)[key] = channel.id

        elif key == "mod_role_id":
            try:
                role = await RoleConverter().convert(ctx, value)
            except RoleNotFound:
                role = None

            if role is None:
                Lang.lang(self, 'mod_role_id')
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
            Config.get(self)[key] = role.id

        elif key == "version":
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'version_cant_changed', key))

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_fantasy_set.command(name="default")
    async def cmd_set_default(self, ctx, platform_name, league_id: int = None):
        if platform_name.lower() == "del":
            self.default_league = -1
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        platform = await self.parse_platform(platform_name, ctx)
        if platform is None:
            return

        for k, el in self.leagues.items():
            if el.league_id == league_id and el.platform == platform:
                self.default_league = k
                self.save()
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
                break
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_id_not_found", league_id))

    @cmd_fantasy_set.command(name="add")
    async def cmd_set_add(self, ctx, platform_name, league_id: int,
                          commish: Union[Member, User, str] = None):
        platform = await self.parse_platform(platform_name, ctx)
        if platform is None:
            return

        if platform == Platform.ESPN and not Config.get(self)["espn_credentials"]["espn_s2"] \
                and not Config.get(self)["espn_credentials"]["swid"]:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "credentials_first", league_id))
            return

        try:
            with ctx.typing():
                league = await create_league(self, platform, league_id, commish)
        except (ValueError, IndexError):
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "api_error", league_id))
            return

        if not league.name:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_add_fail", league_id, platform.name))
        else:
            max_id = max(self.leagues, default=-1) + 1
            self.leagues[max_id] = league
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            com = Lang.lang(self, "nobody") if commish is None or not commish else get_best_username(commish)
            await ctx.send(Lang.lang(self, "league_added", get_best_username(com), league.name))

    @cmd_fantasy_set.command(name="del")
    async def cmd_set_del(self, ctx, league_id: int, platform_name: Platform = None):
        platform = await self.parse_platform(platform_name, ctx)
        to_remove_key = None
        to_remove_league = None
        for k, el in self.leagues.items():
            if el.league_id != league_id:
                continue

            if platform is not None and el.platform != platform:
                continue

            to_remove_key = k
            to_remove_league = el

        if to_remove_key is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "league_id_not_found", league_id))
        else:
            del self.leagues[to_remove_key]
            if self.default_league == to_remove_key:
                self.default_league = -1
            self.save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            com = get_best_username(to_remove_league.commish) \
                if to_remove_league.commish is not None else Lang.lang(self, "unknown")
            await ctx.send(Lang.lang(self, "league_removed", com, to_remove_league.name))
