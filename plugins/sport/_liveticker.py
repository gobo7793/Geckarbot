import asyncio

import discord
from discord.ext import commands

from botutils.stringutils import paginate
from botutils.utils import add_reaction
from data import Lang, Config
from subsystems.liveticker import TeamnameDict, LTSource, PlayerEventEnum, LivetickerKickoff, LivetickerUpdate, \
    LivetickerFinish
from subsystems.reactions import ReactionAddedEvent


# pylint: disable=no-member
class _Liveticker:

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
        for _, _, c_reg in list(self.bot.liveticker.search_coro(plugins=[self.get_name()])):
            c_reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _live_coro(self, event):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        if isinstance(event, LivetickerKickoff):
            # Kickoff-Event
            match_msgs = []
            for match in event.matches:
                predictions = await self._get_predictions(match.home_team.long_name,
                                                          match.away_team.long_name, match.kickoff)
                match_msg = f"{match.home_team.emoji} {match.home_team.long_name} - " \
                            f"{match.away_team.emoji} {match.away_team.long_name}"
                if predictions:
                    match_msg += f"\n{predictions}"
                match_msgs.append(match_msg)
            msgs = paginate(match_msgs,
                            prefix=Lang.lang(self, 'liveticker_prefix_kickoff', event.league,
                                             event.kickoff.strftime('%H:%M')))
            for msg in msgs:
                await sport.send(msg)
        elif isinstance(event, LivetickerUpdate):
            # Intermediate-Event
            if not Config().get(self)['liveticker'].get('do_intermediate_updates', True):
                return
            if not event.matches:
                return
            event_filter = Config().get(self)['liveticker']['tracked_events']
            match_msgs = []
            other_matches = []
            for match in event.matches:
                events_msg = " / ".join(e.display() for e in match.new_events
                                        if PlayerEventEnum(type(e).__base__).name in event_filter)
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
    async def cmd_teamname_add(self, ctx, long_name: str, short_name: str = None, abbr: str = None, emoji: str = None,
                               *alternatives: str):
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
