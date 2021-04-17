import calendar
import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient
from botutils.stringutils import paginate
from botutils.utils import add_reaction, helpstring_helper
from data import Lang, Config
from subsystems.helpsys import DefaultCategories
from subsystems.liveticker import LivetickerKickoff, LivetickerUpdate, LivetickerFinish, LTSource, PlayerEventEnum


class Plugin(BasePlugin, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category=DefaultCategories.SPORT)
        self.logger = logging.getLogger(__name__)
        self.can_reload = True
        self._update_config()

    def default_config(self):
        return {
            'cfg_version': 1,
            'sport_chan': 0,
            'leagues': {"bl1": ["bl", "1bl", "buli"], "bl2": ["2bl"], "bl3": ["3fl"], "uefanl": []},
            'liveticker': {
                'leagues': {"oldb": [], "espn": []},
                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']
            }
        }

    def default_storage(self, container=None):
        return []

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def command_description(self, command):
        name = "_".join(command.qualified_name.split())
        lang_name = "description_{}".format(name)
        result = Lang.lang(self, lang_name)
        if result != lang_name and name == "fußball":
            result = Lang.lang(self, lang_name, ", ".join(Config().get(self)['leagues'].keys()))
        else:
            result = Lang.lang(self, "help_{}".format(name))
        return result

    @commands.command(name="kicker")
    async def cmd_kicker_table(self, ctx):
        now = datetime.now()
        if now.month < 3 or now.month > 7:
            at_values = "[{}]({})".format(Lang.lang(self, 'kicker_ATBL'), Lang.lang(self, 'kicker_ATBL_link'))
        else:
            at_values = "[{}]({})\n[{}]({})\n[{}]({})" \
                .format(Lang.lang(self, 'kicker_ATBL'), Lang.lang(self, 'kicker_ATBL_link'),
                        Lang.lang(self, 'kicker_ATBLM'), Lang.lang(self, 'kicker_ATBLM_link'),
                        Lang.lang(self, 'kicker_ATBLQ'), Lang.lang(self, 'kicker_ATBLQ_link'))

        embed = discord.Embed(title=Lang.lang(self, 'kicker_title'))
        embed.add_field(name=Lang.lang(self, 'kicker_DE'),
                        value="[{}]({})\n[{}]({})\n"
                              "[{}]({})\n[{}]({})"
                        .format(Lang.lang(self, 'kicker_1BL'), Lang.lang(self, 'kicker_1BL_link'),
                                Lang.lang(self, 'kicker_2BL'), Lang.lang(self, 'kicker_2BL_link'),
                                Lang.lang(self, 'kicker_3FL'), Lang.lang(self, 'kicker_3FL_link'),
                                Lang.lang(self, 'kicker_DFBP'), Lang.lang(self, 'kicker_DFBP_link')))
        embed.add_field(name=Lang.lang(self, 'kicker_AT'), value=at_values)
        embed.add_field(name=Lang.lang(self, 'kicker_EU'),
                        value="[{}]({})\n[{}]({})".format(
                            Lang.lang(self, 'kicker_CL'), Lang.lang(self, 'kicker_CL_link'),
                            Lang.lang(self, 'kicker_EL'), Lang.lang(self, 'kicker_EL_link')))
        await ctx.send(embed=embed)

    # todo: read directly from sheets
    @commands.command(name="tippspiel")
    async def cmd_tippspiel(self, ctx):
        await ctx.send(Lang.lang(self, 'tippspiel_output'))

    @commands.command(name="fußball", aliases=["fusselball"])
    async def cmd_soccer_livescores(self, ctx, league, allmatches=None):
        if league not in Config().get(self)['leagues']:
            for leag, aliases in Config().get(self)['leagues'].items():
                if league in aliases:
                    league = leag
                    break
            else:
                await ctx.send(Lang.lang(self, 'league_not_found', ", ".join(Config().get(self)['leagues'])))
                return
        matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(league))
        finished, running, upcoming = [], [], []
        for match in matches:
            if match.get('MatchIsFinished', False):
                finished.append(match)
            else:
                try:
                    time = datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
                except (ValueError, TypeError):
                    pass
                else:
                    if time < datetime.now():
                        running.append(match)
                    else:
                        upcoming.append(match)

        def match_msg(m):
            dt = datetime.strptime(m.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            weekday = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][dt.weekday()]
            time_ = dt.strftime("%H:%M")
            team_h = m.get('Team1', {}).get('TeamName')
            team_a = m.get('Team2', {}).get('TeamName')
            goals = m.get('Goals', [])
            goals_h = max(0, *(x.get('ScoreTeam1', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            goals_a = max(0, *(x.get('ScoreTeam2', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            return "{}. {} | {} [{}:{}] {}".format(weekday, time_, team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title=Lang.lang(self, 'soccer_title', league))
        running_msg = "\n".join(match_msg(m) for m in running)
        if running_msg:
            embed.description = "\n".join(match_msg(m) for m in running)
        if allmatches in ["all", "full"] or not running_msg:
            finished_msg = "\n".join(match_msg(m) for m in finished)
            upcoming_msg = "\n".join(match_msg(m) for m in upcoming)
            if finished_msg:
                embed.add_field(name=Lang.lang(self, 'match_finished'), value=finished_msg, inline=False)
            if upcoming_msg:
                embed.add_field(name=Lang.lang(self, 'match_upcoming'), value=upcoming_msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buli")
    async def cmd_buli_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'bl1', allmatches)

    @commands.command(name="buli2")
    async def cmd_buli2_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'bl2', allmatches)

    @commands.command(name="matches")
    async def cmd_matches_24h(self, ctx):
        async with ctx.typing():
            msg = ""
            for league in Config().get(self)['leagues'].keys():
                matches = restclient.Client("https://www.openligadb.de/api").make_request(
                    "/getmatchdata/{}".format(league))
                league_msg = ""
                for match in matches:
                    try:
                        time = datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
                    except (ValueError, TypeError):
                        continue
                    else:
                        now = datetime.now()
                        if not match.get('MatchIsFinished', True) \
                                and now + timedelta(hours=-2) < time < now + timedelta(days=1):
                            league_msg += "{} {} | {} - {}\n".format(
                                calendar.day_abbr[time.weekday()],
                                time.strftime("%H:%M Uhr"),
                                match.get('Team1', {}).get('TeamName'),
                                match.get('Team2', {}).get('TeamName'))
                if league_msg:
                    msg += "{}\n{}\n".format(matches[0].get('LeagueName', league), league_msg)
            if not msg:
                msg = Lang.lang(self, 'no_matches_24h')
        await ctx.send(msg)

    @commands.group(name="liveticker")
    async def cmd_liveticker(self, ctx):
        if ctx.invoked_subcommand is None:
            _, _, liveticker_regs = self.bot.liveticker.search_coro(plugins=[self.get_name()])
            for c_reg in liveticker_regs:
                c_reg.deregister()
            msg = await ctx.send(Lang.lang(self, 'liveticker_start'))
            for source, leagues in Config().get(self)['liveticker']['leagues'].items():
                for league in leagues:
                    reg_ = await self.bot.liveticker.register(league=league, raw_source=source, plugin=self,
                                                              coro=self._live_coro, periodic=True)
                    next_exec = reg_.next_execution()
                    if next_exec:
                        next_exec = next_exec[0].strftime('%d.%m.%Y - %H:%M')
                    await msg.edit(content=f"{msg.content}\n{league} - Next: {next_exec}")
            Config().get(self)['sport_chan'] = ctx.channel.id
            Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_liveticker.command(name="add")
    async def cmd_liveticker_add(self, ctx, source, league):
        try:
            LTSource(source)
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "err_invalid_src"))
        else:
            if league not in Config().get(self)['liveticker']['leagues'].get(source, []):
                if not Config().get(self)['liveticker']['leagues'].get(source):
                    Config().get(self)['liveticker']['leagues'][source] = []
                Config().get(self)['liveticker']['leagues'][source].append(league)
                Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_liveticker.command(name="del")
    async def cmd_liveticker_del(self, ctx, source, league):
        if source in Config().get(self)['liveticker']['leagues'] and \
                league in Config().get(self)['liveticker']['leagues'][source]:
            Config().get(self)['liveticker']['leagues'][source].remove(league)
            Config().save(self)

            for _, _, c_reg in self.bot.liveticker.search_coro(leagues=[league], sources=[LTSource(source)],
                                                               plugins=[self.get_name()]):
                c_reg.deregister()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    @cmd_liveticker.command(name="list")
    async def cmd_liveticker_list(self, ctx):
        msgs = []
        for source, leagues in Config().get(self)['liveticker']['leagues'].items():
            leagues_str = " / ".join(leagues)
            msgs.append(f"{source} ({len(leagues)}) | {leagues_str}")
        for msg in paginate(msgs, prefix="**Liveticker**\n", if_empty="-"):
            await ctx.send(msg)

    @cmd_liveticker.command(name="toggle")
    async def cmd_liveticker_toggle(self, ctx, event: str):
        if event == "list":
            await self.cmd_liveticker_toggle_list(ctx)
            return
        event = event.upper()
        if event in Config().get(self)['liveticker']['tracked_events']:
            Config().get(self)['liveticker']['tracked_events'].remove(event)
            Config().save(self)
            await add_reaction(ctx.message, Lang.EMOJI['mute'])
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        elif event in PlayerEventEnum.__members__:
            Config().get(self)['liveticker']['tracked_events'].append(event)
            Config().save(self)
            await add_reaction(ctx.message, Lang.EMOJI['unmute'])
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)

    async def cmd_liveticker_toggle_list(self, ctx):
        events = []
        for event in PlayerEventEnum.__members__.keys():
            if event in Config().get(self)['liveticker']['tracked_events']:
                events.append(f"{Lang.EMOJI['unmute']} {event}")
            else:
                events.append(f"{Lang.EMOJI['mute']} {event}")
        await ctx.send("\n".join(events))

    async def _live_coro(self, event):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        if isinstance(event, LivetickerKickoff):
            # Kickoff-Event
            match_msgs = []
            for match in event.matches:
                match_msgs.append(f"{match.home_team} - {match.away_team}")
            msgs = paginate(match_msgs,
                            prefix=Lang.lang(self, 'liveticker_prefix_kickoff', event.league,
                                             event.kickoff.strftime('%H:%M')))
            for msg in msgs:
                await sport.send(msg)
        elif isinstance(event, LivetickerUpdate):
            # Intermediate-Event
            if not event.matches:
                return
            event_filter = Config().get(self)['liveticker']['tracked_events']
            match_msgs = []
            other_matches = []
            for match in event.matches:
                match_msg = "{} | {} - {} | {}:{}".format(match.minute, match.home_team, match.away_team,
                                                          *match.score.values())
                events_msg = " / ".join(e.display() for e in match.new_events
                                        if PlayerEventEnum(type(e)).name in event_filter)
                if events_msg:
                    match_msgs.append("**{}**\n{}".format(match_msg, events_msg))
                else:
                    other_matches.append(match_msg)
            if other_matches:
                match_msgs.append("**{}:** {}".format(Lang.lang(self, 'liveticker_unchanged'),
                                                      " \u2014\u2014 ".join(other_matches)))
            msgs = paginate(match_msgs, prefix=Lang.lang(self, 'liveticker_prefix', event.league))
            for msg in msgs:
                await sport.send(msg)
        elif isinstance(event, LivetickerFinish):
            # Finished-Event
            match_msgs = []
            for match in event.matches:
                match_msgs.append(f"{match.home_team} - {match.away_team}")
            msgs = paginate(match_msgs,
                            prefix=Lang.lang(self, 'liveticker_prefix_finished', event.league))
            for msg in msgs:
                await sport.send(msg)

    def _update_config(self):
        if Config().get(self).get('cfg_version', 0) < 1:
            Config().get(self)['liveticker'] = {'leagues': Config().get(self)['liveticker_leagues'],
                                                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']}
            del Config().get(self)['liveticker_leagues']
            Config().get(self)['cfg_version'] = 1
        Config().save(self)
