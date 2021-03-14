import logging
import re
from datetime import datetime
from enum import IntEnum
from typing import Union

import discord
from discord.ext import commands
from discord.ext.commands import ChannelNotFound, TextChannelConverter, RoleConverter, RoleNotFound

from base import BasePlugin, NotFound
from botutils import permchecks, sheetsclient, utils, timeutils
from botutils.converters import get_best_user, get_plugin_by_name
from botutils.stringutils import paginate, clear_link
from data import Storage, Lang, Config


class DscState(IntEnum):
    """DSC states"""
    NA = 0
    Voting = 1
    Sign_up = 2


def dsc_set_checks():
    def predicate(ctx):
        plugin = get_plugin_by_name(__name__.rsplit(".", 1)[1])
        if (not permchecks.check_mod_access(ctx.author)
                and Config.get(plugin)['mod_role_id'] != 0
                and Config.get(plugin)['mod_role_id'] not in [role.id for role in ctx.author.roles]):
            raise commands.BotMissingAnyRole([*Config().MOD_ROLES, Config.get(plugin)['mod_role_id']])
        if Config.get(plugin)['channel_id'] != 0 and Config.get(plugin)['channel_id'] != ctx.channel.id:
            raise commands.CheckFailure()
        return True

    return commands.check(predicate)


class Plugin(BasePlugin, name="Discord Song Contest"):
    """Commands for the DSC"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category="DSC")
        self.log = logging.getLogger(__name__)

        self.presence = None
        if Storage.get(self)["state"] == DscState.Voting:
            self.register_presence()

        self._fill_rule_link()
        Storage().save(self)

    def default_config(self):
        return {
            'rule_cell': "Aktuell!E2",
            'contestdoc_id': "1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8",
            'winners_range': "Hall of Fame!B4:D200",
            'channel_id': 0,
            'mod_role_id': 0
        }

    def default_storage(self):
        return {
            'rule_link': None,
            'host_id': None,
            'state': DscState.NA,
            'yt_link': None,
            'points': None,
            'date': datetime.now(),
            'status': None
        }

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

    def get_api_client(self):
        """Returns a client to access Google Sheets API for the dsc contestdoc sheet"""
        return sheetsclient.Client(self.bot, Config.get(self)['contestdoc_id'])

    def _get_doc_link(self):
        return "https://docs.google.com/spreadsheets/d/{}".format(Config.get(self)['contestdoc_id'])

    def _get_rule_link(self):
        try:
            c = self.get_api_client()
            values = c.get(Config.get(self)['rule_cell'])
            return values[0][0]
        except IndexError:
            self.log.error("Can't read rules link from Contestdoc sheet. "
                           "Is Google Sheets not reachable or do you set the wrong cell?")
            return ""

    def _fill_rule_link(self):
        if not Storage.get(self)['rule_link']:
            Storage.get(self)['rule_link'] = self._get_rule_link()

    def register_presence(self):
        """Registers the presence message"""
        self.presence = self.bot.presence.register(Lang.lang(self, "presence_voting"))

    def deregister_presence(self):
        """Deregisters the presence message"""
        self.bot.presence.deregister(self.presence)

    @commands.group(name="dsc")
    async def cmd_dsc(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('dsc info'))

    @cmd_dsc.command(name="rules", aliases=["regeln"])
    async def cmd_dsc_rules(self, ctx):
        self._fill_rule_link()
        await ctx.send(f"<{Storage.get(self)['rule_link']}>")

    @cmd_dsc.command(name="status")
    async def cmd_dsc_status(self, ctx):
        if Storage.get(self)['status']:
            status_msg = Lang.lang(self, 'status_base', Storage.get(self)['status'])
        else:
            status_msg = Lang.lang(self, 'status_base', Lang.lang(self, 'status_none'))

        await ctx.send(status_msg)

    @cmd_dsc.command(name="winners")
    async def cmd_dsc_winners(self, ctx):
        c = self.get_api_client()
        winners = c.get(Config.get(self)['winners_range'])

        w_msgs = []
        regex = re.compile(r"\d+")
        for w in winners[1:]:
            if w[0] is None or not w[0]:
                continue

            m0 = regex.findall(w[0])
            m2 = regex.findall(w[2])
            no = m0[0]
            dt = datetime(int(m0[2]), int(m0[1]), 1)
            participator_coutn = m0[3]
            winner_name = w[1]
            pts_winner = int(m2[0])
            pts_max = int(m2[1])
            pts_percentage = round(pts_winner / pts_max * 100)

            w_msgs.append(Lang.lang(self, 'winner_msg', no, winner_name, pts_winner, pts_max, pts_percentage,
                                    participator_coutn, dt.month, dt.year))

        for m in paginate(w_msgs, Lang.lang(self, 'winner_prefix')):
            await ctx.send(m)

    @cmd_dsc.command(name="info")
    async def cmd_dsc_info(self, ctx):
        date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y, %H:%M'))
        if not Storage.get(self)['host_id']:
            await ctx.send(Lang.lang(self, 'must_set_host'))
            return

        host_nick = get_best_user(Storage.get(self)['host_id'])

        embed = discord.Embed()
        embed.add_field(name=Lang.lang(self, 'current_host'), value=host_nick.mention)
        if Storage.get(self)['status']:
            embed.description = Storage.get(self)['status']

        if Storage.get(self)['state'] == DscState.Sign_up:
            date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y')) \
                if Storage.get(self)['date'] > datetime.now() \
                else ""
            embed.title = Lang.lang(self, 'signup_phase_info', date_out_str)
            embed.add_field(name=Lang.lang(self, 'sign_up'), value=self._get_doc_link())

        elif Storage.get(self)['state'] == DscState.Voting:
            embed.title = Lang.lang(self, 'voting_phase_info', date_out_str)
            embed.add_field(name=Lang.lang(self, 'all_songs'), value=self._get_doc_link())
            embed.add_field(name=Lang.lang(self, 'yt_playlist'), value=Storage.get(self)['yt_link'])
            embed.add_field(name=Lang.lang(self, 'points'), value=Storage.get(self)['points'])

        else:
            await ctx.send(Lang.lang(self, 'config_error_reset'))
            await ctx.invoke(self.bot.get_command("configdump"), self.get_name())
            await ctx.invoke(self.bot.get_command("storagedump"), self.get_name())
            return

        await ctx.send(embed=embed)

    @cmd_dsc.group(name="set", invoke_without_command=True)
    @dsc_set_checks()
    async def cmd_dsc_set(self, ctx, *args):
        if len(args) > 2 and args[1] == "until":
            # !dsc set <signup|voting> until <date>
            await ctx.invoke(self.bot.get_command('dsc set state'), args[0])
            await ctx.invoke(self.bot.get_command('dsc set date'), args[2:])

        elif ctx.invoked_subcommand is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd_dsc_set.command(name="host")
    async def cmd_dsc_set_host(self, ctx, user: Union[discord.Member, discord.User]):
        Storage.get(self)['host_id'] = user.id
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _dsc_save_state(self, ctx, new_state: DscState):
        Storage.get(self)['state'] = new_state
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="state")
    async def cmd_dsc_set_state(self, ctx, state):
        if state.lower() == "voting":
            await self._dsc_save_state(ctx, DscState.Voting)
            self.register_presence()
        elif state.lower() == "signup":
            await self._dsc_save_state(ctx, DscState.Sign_up)
            self.deregister_presence()
        else:
            await ctx.send(Lang.lang(self, 'invalid_phase'))

    @cmd_dsc_set.command(name="yt")
    async def cmd_dsc_set_yt_link(self, ctx, link):
        link = clear_link(link)
        Storage.get(self)['yt_link'] = link
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="date")
    async def cmd_dsc_set_date(self, ctx, *args):
        date = timeutils.parse_time_input(args, end_of_day=True)
        Storage.get(self)['date'] = date
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="status")
    async def cmd_dsc_set_status(self, ctx, *, message):
        Storage.get(self)['status'] = message
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="points")
    async def cmd_dsc_set_points(self, ctx, *points):
        Storage.get(self)['points'] = "-".join(points)
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="config")
    async def cmd_dsc_set_config(self, ctx, key="", value=""):
        if not key and not value:
            msg = []
            for key in Config.get(self):
                msg.append("{}: {}".format(key, Config.get(self)[key]))
            for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
                await ctx.send(msg)
            return

        if key and not value:
            key_value = Config.get(self).get(key, None)
            if key_value is None:
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'key_not_exist', key))
            else:
                await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
                await ctx.send(key_value)
            return

        if key == "channel_id":
            try:
                channel = await TextChannelConverter().convert(ctx, value)
            except ChannelNotFound:
                channel = None

            if channel is None:
                Lang.lang(self, 'channel_id')
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = channel.id

        elif key == "mod_role_id":
            try:
                role = await RoleConverter().convert(ctx, value)
            except RoleNotFound:
                role = None

            if role is None:
                Lang.lang(self, 'songmaster_id')
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = role.id

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
