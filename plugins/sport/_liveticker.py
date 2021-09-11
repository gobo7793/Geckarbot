import asyncio
import logging
from typing import List

import discord
from discord.ext import commands

from botutils.stringutils import paginate
from botutils.utils import add_reaction
from data import Lang, Config
from subsystems.liveticker import TeamnameDict, LTSource, PlayerEventEnum, LivetickerKickoff, LivetickerMidgame, \
    LivetickerFinish, LivetickerEvent, League
from subsystems.reactions import ReactionAddedEvent

logger = logging.getLogger(__name__)


class _Liveticker:

    def __init__(self, bot, get_name, _get_predictions):
        self.bot = bot
        self.get_name = get_name
        self._get_predictions = _get_predictions

    @commands.group(name="liveticker")
    async def cmd_liveticker(self, ctx):
        if ctx.invoked_subcommand is None:
            for c_reg in self.bot.liveticker.search_coro(plugin_names=[self.get_name()]):
                # Show dialog for actions
                leagues = (str(l_reg.league) for l_reg in c_reg.l_regs)
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
                break
            else:
                # Start liveticker
                await ctx.send(Lang.lang(self, 'liveticker_start'))
                leagues = []
                for raw_source, keys in Config().get(self)['liveticker']['leagues'].items():
                    if not keys:
                        continue
                    source = LTSource(raw_source)
                    leagues.extend([League(source=source, key=key) for key in keys])
                if leagues:
                    await self.bot.liveticker.register_coro(plugin=self, coro=self._live_coro, leagues=leagues,
                                                            interval=Config().get(self)['liveticker']['interval'])
                leagues_str = ", ".join(f"{league.source.value}/{league.key}" for league in leagues)
                await ctx.send(Lang.lang(self, 'liveticker_started', len(leagues), leagues_str))
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
                for c_reg in list(self.bot.liveticker.search_coro(plugin_names=[self.get_name()])):
                    c_reg.deregister()
            event.data['react'] = True
            event.callback.deregister()
            for emoji in actions:
                await event.message.remove_reaction(emoji, self.bot.user)
            await add_reaction(event.message, Lang.CMDSUCCESS)

    @cmd_liveticker.command(name="add")
    async def cmd_liveticker_add(self, ctx, raw_source, key):
        try:
            source = LTSource(raw_source)
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "err_invalid_src"))
            return
        if key not in Config().get(self)['liveticker']['leagues'].get(raw_source, []):
            Config().get(self)['liveticker']['leagues'].setdefault(raw_source, []).append(key)
            Config().save(self)
        for c_reg in self.bot.liveticker.search_coro(plugin_names=[self.get_name()]):
            c_reg.add_league(League(source, key))
            await ctx.send(Lang.lang(self, 'liveticker_added_running'))
            break
        else:
            await ctx.send(Lang.lang(self, 'liveticker_added'))

    @cmd_liveticker.command(name="del")
    async def cmd_liveticker_del(self, ctx, source, league):
        if league in Config().get(self)['liveticker']['leagues'].get(source, []):
            Config().get(self)['liveticker']['leagues'][source].remove(league)
            Config().save(self)
            for c_reg in self.bot.liveticker.search_coro(league_keys=[league], sources=[LTSource(source)],
                                                         plugin_names=[self.get_name()]):
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
        if event in ("ALL", "ALLE", "UPDATES"):
            if Config().get(self)['liveticker'].get('do_intermediate_updates', True):
                Config().get(self)['liveticker']['do_intermediate_updates'] = False
                await add_reaction(ctx.message, Lang.EMOJI['mute'])
            else:
                Config().get(self)['liveticker']['do_intermediate_updates'] = True
                await add_reaction(ctx.message, Lang.EMOJI['unmute'])
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            Config().save(self)
        elif event in Config().get(self)['liveticker']['tracked_events']:
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
        if Config().get(self)['liveticker'].get('do_intermediate_updates', True):
            events.append(Lang.lang(self, 'liveticker_updates_enabled'))
        else:
            events.append(Lang.lang(self, 'liveticker_updates_disabled'))
        for event in PlayerEventEnum.__members__:
            if event in Config().get(self)['liveticker']['tracked_events']:
                events.append(f"- {Lang.EMOJI['unmute']} {event}")
            else:
                events.append(f"- {Lang.EMOJI['mute']} {event}")
        await ctx.send("\n".join(events))

    @cmd_liveticker.command(name="stop")
    async def cmd_liveticker_stop(self, ctx):
        for c_reg in list(self.bot.liveticker.search_coro(plugin_names=[self.get_name()])):
            await c_reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_liveticker.command(name="interval")
    async def cmd_liveticker_interval(self, ctx, new_interval: int):
        Config().get(self)['liveticker']['interval'] = new_interval
        Config().save(self)
        for c_reg in list(self.bot.liveticker.search_coro(plugin_names=[self.get_name()])):
            c_reg.interval = new_interval
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_liveticker.command(name="matches", aliases=["spiele"])
    async def cmd_liveticker_matches(self, ctx):
        msg_lines = []
        for l_reg in self.bot.liveticker.search_league():
            msg_lines.append(f"**{l_reg.league_key}**")
            if len(l_reg.kickoffs) == 0:
                msg_lines.append(Lang.lang(self, 'no_matches'))
            for kickoff, matches in l_reg.kickoffs.items():
                msg_lines.append(f"{kickoff:%a. %d.%m.%Y, %H:%M Uhr}")
                msg_lines.extend(f"- {m.home_team.long_name} - {m.away_team.long_name}" for m in matches.values())
        for msg in paginate(msg_lines, if_empty=Lang.lang(self, 'no_matches_found')):
            await ctx.send(msg)

    async def _live_coro(self, updates: List[LivetickerEvent]):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        match_msgs = []
        for event in updates:
            if isinstance(event, LivetickerKickoff):
                match_msgs.extend(await self.kickoff_msg(event))
            elif isinstance(event, LivetickerMidgame):
                if not Config().get(self)['liveticker'].get('do_intermediate_updates', True):
                    continue
                if not event.matches:
                    continue
                match_msgs.extend(self.midgame_msg(event=event,
                                                   event_filter=Config().get(self)['liveticker']['tracked_events']))
            elif isinstance(event, LivetickerFinish):
                match_msgs.extend(self.finished_msg(event))
        msgs = paginate(match_msgs)
        for msg in msgs:
            await sport.send(msg)

    async def kickoff_msg(self, event: LivetickerKickoff) -> List[str]:
        """Returns the message for a kickoff event"""
        match_msgs = [Lang.lang(self, 'liveticker_prefix_kickoff', event.league, event.kickoff.strftime('%H:%M'))]
        for match in event.matches:
            predictions = await self._get_predictions(match.home_team,
                                                      match.away_team, match.kickoff)
            match_msg = f"{match.home_team.emoji} {match.home_team.long_name} - " \
                        f"{match.away_team.emoji} {match.away_team.long_name}"
            if predictions:
                match_msg += f"\n{predictions}"
            match_msgs.append(match_msg)
        return match_msgs

    def midgame_msg(self, event: LivetickerMidgame, event_filter: List[str]) -> List[str]:
        """Returns the message for a midgame event"""
        match_msgs = [Lang.lang(self, 'liveticker_prefix', event.league)]
        other_matches = []
        for match in event.matches:
            events_msg = " / ".join(e.display() for e in event.event_dict[match]
                                    if PlayerEventEnum(type(e).__base__).name in event_filter)
            if events_msg:
                match_msg = "{} | {} {} - {} {} | {}:{}".format(match.minute, match.home_team.emoji,
                                                                match.home_team.long_name, match.away_team.emoji,
                                                                match.away_team.long_name, *match.score.values())
                match_msgs.append("**{}**\n{}".format(match_msg, events_msg))
            else:
                match_msg = "{2}-{3} {0} - {1} | {5}:{6} ({4})".format(match.home_team.abbr, match.away_team.abbr,
                                                                       match.home_team.emoji, match.away_team.emoji,
                                                                       match.minute, *match.score.values())
                other_matches.append(match_msg)
        if other_matches:
            match_msgs.append("{}: {}".format(Lang.lang(self, 'liveticker_unchanged'),
                                              " \u2014 ".join(other_matches)))
        return match_msgs

    def finished_msg(self, event: LivetickerFinish) -> List[str]:
        """Returns the message for a finished event"""
        match_msgs = [Lang.lang(self, 'liveticker_prefix_finished', event.league)]
        for match in event.matches:
            match_msgs.append(f"{match.score[match.home_team_id]}:{match.score[match.away_team_id]} | "
                              f"{match.home_team.emoji} {match.home_team.short_name} - {match.away_team.emoji} "
                              f"{match.away_team.short_name}")
        return match_msgs

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
    async def cmd_teamname_add(self, ctx, long_name: str, *alternatives: str, short_name: str = None,
                               abbr: str = None, emoji: str = None):
        try:
            teamnamedict = self.bot.liveticker.teamname_converter.add(long_name, short_name, abbr, emoji,
                                                                      other=alternatives)
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
