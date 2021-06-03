import asyncio
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
from subsystems.liveticker import LivetickerKickoff, LivetickerUpdate, LivetickerFinish, LTSource, PlayerEventEnum, \
    Match, MatchStatus, TeamnameDict
from subsystems.reactions import ReactionAddedEvent


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
            'cfg_version': 2,
            'sport_chan': 0,
            'league_aliases': {"bl": ["ger.1", "espn"]},
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
    async def cmd_soccer_livescores(self, ctx, league: str, raw_source: str = None, allmatches=None):
        source = None
        if raw_source:
            try:
                source = LTSource(raw_source)
            except ValueError:
                if allmatches is None:
                    allmatches = True
                else:
                    await add_reaction(ctx.message, Lang.CMDERROR)
                    return
        if source is None:
            try:
                league, raw_source = Config().get(self)['league_aliases'].get(league, [])
                source = LTSource(raw_source)
            except ValueError:
                await add_reaction(ctx.message, Lang.CMDERROR)
                return

        if source == LTSource.OPENLIGADB:
            try:
                raw_matches = await restclient.Client("https://www.openligadb.de/api")\
                    .request(f"/getmatchdata/{league}")
                matches = [Match.from_openligadb(m) for m in raw_matches]
            except (ValueError, AttributeError):
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
        elif source == LTSource.ESPN:
            raw_matches = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports").request(
                f"/soccer/{league}/scoreboard")
            matches = [Match.from_espn(m) for m in raw_matches.get('events', [])]
        else:
            raise ValueError('Invalid source. Should not happen.')

        if len(matches) == 0:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        finished = [m for m in matches if m.status == MatchStatus.COMPLETED]
        running = [m for m in matches if m.status == MatchStatus.RUNNING]
        upcoming = [m for m in matches if m.status == MatchStatus.UPCOMING]

        def match_msg(m: Match):
            weekday = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][m.kickoff.weekday()]
            time_ = m.kickoff.strftime("%H:%M")
            team_h = m.home_team.long_name
            team_a = m.away_team.long_name
            goals_h = m.score[m.home_team_id]
            goals_a = m.score[m.away_team_id]
            return "{}. {} | {} [{}:{}] {}".format(weekday, time_, team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title=Lang.lang(self, 'soccer_title', league))
        running_msg = "\n".join(match_msg(m) for m in running)
        if running_msg:
            embed.description = "\n".join(match_msg(m) for m in running)
        if allmatches or not running_msg:
            finished_msg = "\n".join(match_msg(m) for m in finished)
            upcoming_msg = "\n".join(match_msg(m) for m in upcoming)
            if finished_msg:
                embed.add_field(name=Lang.lang(self, 'match_finished'), value=finished_msg, inline=False)
            if upcoming_msg:
                embed.add_field(name=Lang.lang(self, 'match_upcoming'), value=upcoming_msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buli")
    async def cmd_buli_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'ger.1', 'espn', allmatches)

    @commands.command(name="buli2")
    async def cmd_buli2_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'ger.2', 'espn', allmatches)

    @commands.command(name="table", alias="tabelle")
    async def cmd_table(self, ctx, league: str, raw_source: str = "espn"):
        try:
            league_name, tables = await self.bot.liveticker.get_standings(league, LTSource(raw_source))
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
        else:
            embed = discord.Embed(title=Lang.lang(self, 'table_title', league_name))
            for group_name, table in tables.items():
                table.sort(key=lambda x: x.rank)
                tables[group_name] = [x.display() for x in table]
            if len(tables) == 1:
                table = list(tables.values())[0]
                if len(table) > 10:
                    embed.add_field(name=Lang.lang(self, 'table_top'), value="\n".join(table[:len(table) // 2]))
                    embed.add_field(name=Lang.lang(self, 'table_bottom'), value="\n".join(table[len(table) // 2:]))
                else:
                    embed.description = "\n".join(table)
            else:
                for group_name, table in tables.items():
                    embed.add_field(name=group_name, value="\n".join(table))
            await ctx.send(embed=embed)

    @commands.command(name="bulitable")
    async def cmd_buli_table(self, ctx):
        await ctx.invoke(self.bot.get_command('table'), 'ger.1', 'espn')

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
            liveticker_regs = list(self.bot.liveticker.search_coro(plugins=[self.get_name()]))
            if liveticker_regs:
                # Show dialog for actions
                leagues = (c_reg.league_reg.league for _, _, c_reg in liveticker_regs)
                actions = "🔀", "🚫"
                description = Lang.lang(self, 'liveticker_running',
                                        Config().bot.get_channel(Config().get(self)['sport_chan']).mention,
                                        ", ".join(leagues))
                embed = discord.Embed(title="Liveticker",
                                      description=description)
                embed.add_field(name=Lang.lang(self, 'liveticker_action_title'),
                                value="\n".join(Lang.lang(self, 'liveticker_action_{}'.format(x)) for x in actions))
                msg = await ctx.send(embed=embed)
                for emoji in actions:
                    await add_reaction(msg, emoji)
                react = self.bot.reaction_listener.register(msg, self._liveticker_reaction,
                                                            data={'user': ctx.author.id, 'react': False})
                await asyncio.sleep(60)
                if react and not react.data['react']:
                    embed.clear_fields()
                    embed.set_footer(text=Lang.lang(self, 'liveticker_action_timeout'))
                    await msg.edit(embed=embed)
                    for emoji in actions:
                        await msg.remove_reaction(emoji, self.bot.user)
                    react.deregister()
                self.logger.debug("ENDE")
            else:
                # Start liveticker
                msg = await ctx.send(Lang.lang(self, 'liveticker_start'))
                for source, leagues in Config().get(self)['liveticker']['leagues'].items():
                    for league in leagues:
                        reg_ = await self.bot.liveticker.register(league=league, raw_source=source, plugin=self,
                                                                  coro=self._live_coro, periodic=True)
                        next_exec = reg_.next_execution()
                        if next_exec:
                            next_exec = next_exec[0].strftime('%d.%m.%Y - %H:%M')
                        await msg.edit(content="{}\n{} - Next: {}".format(msg.content, league, next_exec))
                Config().get(self)['sport_chan'] = ctx.channel.id
                Config().save(self)
                await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _liveticker_reaction(self, event):
        if isinstance(event, ReactionAddedEvent) and event.member.id == event.data['user'] and not event.data['react']:
            actions = "🔀", "🚫"
            if event.emoji.name not in actions:
                return
            embed = event.message.embeds[0]
            embed.clear_fields()
            embed.add_field(name=Lang.lang(self, 'liveticker_action_used'),
                            value=Lang.lang(self, 'liveticker_action_{}'.format(event.emoji)))
            await event.message.edit(embed=embed)
            if event.emoji.name == "🔀":
                # Switching channels
                old_channel = Config().get(self)['sport_chan']
                if event.channel.id != old_channel:
                    await Config().bot.get_channel(old_channel).send(Lang.lang(self, 'liveticker_channel_switched',
                                                                               event.channel.mention))
                    Config().get(self)['sport_chan'] = event.channel.id
                    Config().save(self)
            elif event.emoji.name == "🚫":
                # Stopping liveticker
                for _, _, c_reg in list(self.bot.liveticker.search_coro(plugins=[self.get_name()])):
                    c_reg.deregister()
            event.data['react'] = True
            event.callback.deregister()
            for emoji in actions:
                await event.message.remove_reaction(emoji, self.bot.user)
            await add_reaction(event.message, Lang.CMDSUCCESS)

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
            if list(self.bot.liveticker.search_coro(plugins=[self.get_name()])):
                await self.bot.liveticker.register(league=league, raw_source=source, plugin=self,
                                                   coro=self._live_coro, periodic=True)
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
                break
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
        for event in PlayerEventEnum.__members__:
            if event in Config().get(self)['liveticker']['tracked_events']:
                events.append(f"{Lang.EMOJI['unmute']} {event}")
            else:
                events.append(f"{Lang.EMOJI['mute']} {event}")
        await ctx.send("\n".join(events))

    @cmd_liveticker.command(name="stop")
    async def cmd_liveticker_stop(self, ctx):
        for _, _, c_reg in list(self.bot.liveticker.search_coro(plugins=[self.get_name()])):
            c_reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _live_coro(self, event):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        if isinstance(event, LivetickerKickoff):
            # Kickoff-Event
            match_msgs = []
            for match in event.matches:
                match_msgs.append(f"{match.home_team.emoji} {match.home_team.long_name} - {match.away_team.emoji} "
                                  f"{match.away_team.long_name}")
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
                events_msg = " / ".join(e.display() for e in match.new_events
                                        if PlayerEventEnum(type(e)).name in event_filter)
                if events_msg:
                    match_msg = "{} | {} {} - {} {}| {}:{}".format(match.minute, match.home_team.emoji,
                                                                   match.home_team.long_name, match.away_team.emoji,
                                                                   match.away_team.long_name, *match.score.values())
                    match_msgs.append("**{}**\n{}".format(match_msg, events_msg))
                else:
                    match_msg = "{2}-{3} {0} - {1} | {5}:{6} ({4})".format(match.home_team.abbr, match.away_team.abbr,
                                                                           match.home_team.emoji, match.away_team.emoji,
                                                                           match.minute, *match.score.values())
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
                match_msgs.append(f"{match.score[match.home_team_id]}:{match.score[match.away_team_id]} | "
                                  f"{match.home_team.emoji} {match.home_team.short_name} - {match.away_team.emoji} "
                                  f"{match.away_team.short_name}")
            msgs = paginate(match_msgs,
                            prefix=Lang.lang(self, 'liveticker_prefix_finished', event.league))
            for msg in msgs:
                await sport.send(msg)

    @commands.group(name="teamname")
    async def cmd_teamname(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.cmd_teamname)

    @cmd_teamname.command(name="info")
    async def cmd_teamname_info(self, ctx, *, team: str):
        teamname_dict = self.bot.liveticker.teamname_converter.get(team)
        if not teamname_dict:
            await ctx.send(Lang.lang(self, 'team_not_found'))
        else:
            embed = discord.Embed(title=f"{teamname_dict.emoji} {team}",
                                  description=f"{Lang.lang(self, 'teamname_long')}: {teamname_dict.long_name}\n"
                                              f"{Lang.lang(self, 'teamname_short')}: {teamname_dict.short_name}\n"
                                              f"{Lang.lang(self, 'teamname_abbr')}: {teamname_dict.abbr}")
            if teamname_dict.other:
                embed.set_footer(text=f"{Lang.lang(self, 'teamname_other')}: {', '.join(teamname_dict.other)}")
            await ctx.send(embed=embed)

    @cmd_teamname.command(name="set")
    async def cmd_teamname_set(self, ctx, variant: str, team: str, *, new_name: str):
        variant = variant.lower()
        long = "long", "lang"
        short = "short", "kurz"
        abbr = "abbr", "abbreviation", "abk", "abk.", "abkürzung"
        emoji = "emoji", "wappen"
        saved_team = self.bot.liveticker.teamname_converter.get(team)
        saved_team_new = self.bot.liveticker.teamname_converter.get(new_name)
        if not saved_team:
            await ctx.send(Lang.lang(self, 'team_not_found'))
            return
        if saved_team_new and saved_team_new != saved_team:
            await ctx.send(Lang.lang(self, 'teamname_set_duplicate', new_name, saved_team.long_name))
            return
        if variant in long:
            saved_team.update(long_name=new_name)
        elif variant in short:
            saved_team.update(short_name=new_name)
        elif variant in abbr:
            saved_team.update(abbr=new_name)
        elif variant in emoji:
            saved_team.update(emoji=new_name)
        else:
            await ctx.send(Lang.lang(self, 'teamname_set_variant_invalid', long + short + abbr + emoji))
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_teamname.command(name="add")
    async def cmd_teamname_add(self, ctx, long_name: str, short_name: str = None, abbr: str = None, emoji: str = None):
        try:
            teamnamedict = self.bot.liveticker.teamname_converter.add(long_name, short_name, abbr, emoji)
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        else:
            await ctx.send(Lang.lang(self, 'teamname_added', teamnamedict.long_name))

    @cmd_teamname.command(name="del", alias="remove")
    async def cmd_teamname_del(self, ctx, *, teamname: str):
        teamnamedict: TeamnameDict = self.bot.liveticker.teamname_converter.get(teamname)
        if not teamnamedict:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'team_not_found'))
        teamnamedict.remove(teamname)

    def _update_config(self):
        if Config().get(self).get('cfg_version', 0) < 1:
            Config().get(self)['liveticker'] = {'leagues': Config().get(self)['liveticker_leagues'],
                                                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']}
            del Config().get(self)['liveticker_leagues']
            Config().get(self)['cfg_version'] = 1
            self.logger.debug("Updated config to version 1")
        if Config().get(self).get('cfg_version', 0) < 2:
            leagues = Config().get(self)['leagues']
            league_aliases = {}
            for k, aliases in leagues.items():
                for v in aliases:
                    league_aliases[v] = [k, "oldb"]
            Config().get(self)['league_aliases'] = league_aliases
            del Config().get(self)['leagues']
            Config().get(self)['cfg_version'] = 2
            self.logger.debug("Updated config to version 2")
        Config().save(self)
