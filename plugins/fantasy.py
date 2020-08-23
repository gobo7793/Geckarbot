from enum import IntEnum
import discord

from datetime import datetime
from discord.ext import commands
from conf import Config, Storage, Lang
from botutils import utils, permChecks
from Geckarbot import BasePlugin


class FantasyState(IntEnum):
    """Fantasy states"""
    NA = 0
    Sign_up = 1
    Predraft = 2
    Preseason = 3
    Regular = 4
    Postseason = 5
    Finished = 6


class Plugin(BasePlugin, name="NFL Fantasyliga"):
    """Commands for the Fantasy game"""

    fantasymaster_role_id = 721178888050573352

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

    def default_config(self):
        return {
            "channel_id": 0,
            "mod_role_id": 0
        }

    def default_storage(self):
        return {
            "links": [""],
            "commishs": [""],
            "supercommish": 0,
            "state": FantasyState.NA,
            "date": datetime.now(),
            "status": "",
            "datalink": ""
        }

    def is_single_league(self):
        return self.get_league_cnt() == 1

    def get_league_cnt(self):
        return len(Storage.get(self)["links"])

    @commands.group(name="fantasy", help="Get and manage information about the NFL Fantasy Game",
                    description="Get the information about the Fantasy Game or manage it. "
                                "Command only works in nfl-fantasy channel."
                                "Managing information is only permitted for fantasymasters.")
    async def fantasy(self, ctx):
        if Config.get(self)['channel_id'] != 0 and Config.get(self)['channel_id'] != ctx.channel.id:
            raise commands.CheckFailure()

        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('fantasy info'))

    @fantasy.command(name="link", help="Get the link to the Fantasy Leagues")
    async def link(self, ctx):
        def to_msg(number):
            return "{}: <{}>".format(Lang.lang(self, "league_name", number + 1), Storage.get(self)["links"][number])

        prefix_str_name = "league_link" if self.is_single_league() else "league_link_multileague"
        for msg in utils.paginate(range(0, self.get_league_cnt()),
                                  prefix=Lang.lang(self, prefix_str_name), f=to_msg):
            await ctx.send(msg)

    @fantasy.command(name="status", help="Get the current information about the current fantasy state")
    async def status(self, ctx):
        if Storage.get(self)['status']:
            status_msg = Lang.lang(self, 'status_base', Storage.get(self)['status'])
        else:
            status_msg = Lang.lang(self, 'status_base', Lang.lang(self, 'status_none'))

        await ctx.send(status_msg)

    @fantasy.command(name="info", help="Get information about the NFL Fantasy Game")
    async def info(self, ctx):
        def add_commishs():
            for no in range(0, self.get_league_cnt()):
                field_name = "{} {} {}".format(Lang.lang(self, "commish"), Lang.lang(self, "league_name"), no + 1)
                embed.add_field(name=field_name, value=commishs[no])

        def add_links():
            for no in range(0, self.get_league_cnt()):
                field_name = "{} {}".format(Lang.lang(self, "league_name"), no + 1)
                embed.add_field(name=field_name, value=Storage.get(self)["links"][no],
                                inline=False if no == 0 else True)

        date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y, %H:%M'))
        if not Storage.get(self)['commishs'][0]:
            await ctx.send(Lang.lang(self, 'must_set_commish'))
            return

        commishs = [discord.utils.get(ctx.guild.members, id=cid).mention for cid in Storage.get(self)['commishs']]
        super_commish = discord.utils.get(ctx.guild.members, id=Storage.get(self)['supercommish']).mention

        embed = discord.Embed()
        if Storage.get(self)['status']:
            embed.description = Storage.get(self)['status']

        if Storage.get(self)['state'] == FantasyState.Sign_up:
            date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y')) \
                if Storage.get(self)['date'] > datetime.now() \
                else ""
            embed.title = Lang.lang(self, 'signup_phase_info', date_out_str)
            embed.add_field(name=Lang.lang(self, 'supercommish'), value=super_commish)
            embed.add_field(name=Lang.lang(self, 'sign_up_at'), value=super_commish)

        elif Storage.get(self)['state'] == FantasyState.Predraft:
            embed.title = Lang.lang(self, 'predraft_phase_info', date_out_str)
            add_commishs()
            embed.add_field(name=Lang.lang(self, 'player_database'), value=Storage.get(self)['datalink'], inline=False)

        elif Storage.get(self)['state'] == FantasyState.Preseason:
            embed.title = Lang.lang(self, 'preseason_phase_info', date_out_str)
            add_commishs()
            add_links()

        elif Storage.get(self)['state'] == FantasyState.Regular:
            embed.title = Lang.lang(self, 'regular_phase_info', date_out_str)
            add_commishs()
            add_links()

        elif Storage.get(self)['state'] == FantasyState.Postseason:
            embed.title = Lang.lang(self, 'postseason_phase_info', date_out_str)
            add_commishs()
            add_links()

        elif Storage.get(self)['state'] == FantasyState.Finished:
            embed.title = Lang.lang(self, 'finished_phase_info', date_out_str)

        else:
            await ctx.send(Lang.lang(self, 'config_error_reset'))
            await ctx.invoke(self.bot.get_command("configdump"), self.get_name())
            await ctx.invoke(self.bot.get_command("storagedump"), self.get_name())
            return

        await ctx.send(embed=embed)

    @fantasy.group(name="set", help="Set data about the fantasy game.")
    async def fantasy_set(self, ctx):
        if (not permChecks.check_full_access(ctx.author)
                and Config.get(self)['mod_role_id'] != 0
                and Config.get(self)['mod_role_id'] not in [role.id for role in ctx.author.roles]):
            raise commands.BotMissingAnyRole([*Config().FULL_ACCESS_ROLES, Config.get(self)['mod_role_id']])

        if ctx.invoked_subcommand is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @fantasy_set.command(name="datalink", help="Sets the link for the Players Database")
    async def set_datalink(self, ctx, link):
        link = utils.clear_link(link)
        Storage.get(self)['datalink'] = link
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="link", help="Sets the link for the league #",
                         description="Sets the link for the league #. "
                                     "If the league doesn't exist, a new league will be added.")
    async def set_link(self, ctx, number: int, link):
        if number < 1:
            await ctx.send(Lang.lang(self, "invalid_league", number))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        link = utils.clear_link(link)
        if number > self.get_league_cnt():
            Storage.get(self)['links'].append(link)
            Storage.get(self)['commishs'].append("")
        else:
            Storage.get(self)['links'][number - 1] = link
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="del", help="Removes league #")
    async def set_del(self, ctx, number: int):
        if number < 1 or number > self.get_league_cnt():
            await ctx.send(Lang.lang(self, "league_doesnt_exist", number))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        del(Storage.get(self)['links'][number - 1])
        del(Storage.get(self)['commishs'][number - 1])
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="comm", help="Sets the commissioner for the league #")
    async def set_comm(self, ctx, number: int, commissioner: discord.Member):
        if number < 1:
            await ctx.send(Lang.lang(self, "invalid_league", number))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return
        if number > self.get_league_cnt():
            await ctx.send(Lang.lang(self, "league_doesnt_exist", number))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        Storage.get(self)['commishs'][number - 1] = commissioner.id
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="orga", help="Sets the Fantasy Organisator")
    async def set_orga(self, ctx, organisator: discord.Member):
        Storage.get(self)['supercommish'] = organisator.id
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    async def _save_state(self, ctx, new_state: FantasyState):
        Storage.get(self)['state'] = new_state
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="state", help="Sets the Fantasy state",
                         description="Sets the Fantasy state. "
                                     "Possible states: Sign_Up, Predraft, Preseason, Regular, Postseason, Finished",
                         usage="<sign_up|predraft|preseason|regular|postseason|finished>")
    async def fantasy_set_state(self, ctx, state):
        if state.lower() == "sign_up":
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
            await ctx.send(Lang.lang(self, 'invalid_phase'))

    @fantasy_set.command(name="date", help="Sets the state end date", usage="DD.MM.YYYY [HH:MM]",
                         description="Sets the end date and time for all the phases. "
                                     "If no time is given, 23:59 will be used.")
    async def set_date(self, ctx, date_str, time_str=None):
        if not time_str:
            time_str = "23:59"
        Storage.get(self)['date'] = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="status", help="Sets the status message",
                         description="Sets a status message for additional information. To remove give no message.")
    async def set_status(self, ctx, *message):
        Storage.get(self)['status'] = " ".join(message)
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @fantasy_set.command(name="config", help="Gets or sets general config values for the plugin")
    async def set_config(self, ctx, key="", value=""):
        if not key and not value:
            await ctx.invoke(self.bot.get_command("configdump"), self.get_name())
            return

        if key and not value:
            key_value = Config.get(self).get(key, None)
            if key_value is None:
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'key_not_exists', key))
            else:
                await ctx.message.add_reaction(Lang.CMDSUCCESS)
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
                await ctx.message.add_reaction(Lang.CMDERROR)
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
                await ctx.message.add_reaction(Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = int_value

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
