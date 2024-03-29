import logging
import re
from datetime import datetime
from enum import IntEnum
from typing import Union

from nextcord import Embed, Member, User
from nextcord.ext import commands
from nextcord.ext.commands import ChannelNotFound, TextChannelConverter, RoleConverter, RoleNotFound

from base.configurable import BasePlugin, NotFound
from base.data import Storage, Lang, Config
from botutils import permchecks, sheetsclient, utils, timeutils
from botutils.converters import get_best_user, get_plugin_by_name
from botutils.stringutils import paginate, clear_link, table


class DscState(IntEnum):
    """DSC states"""
    NA = 0
    VOTING = 1
    SIGN_UP = 2


class ConfigError(Exception):
    """
    Raised by build_info_embed if the plugin is not sufficiently configured.
    """
    def __init__(self, lang_key, *args):
        self.lang_key = lang_key
        super().__init__(*args)


def _dsc_set_checks():
    """Checks if dsc set command can be executed"""
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

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category="DSC", category_desc=Lang.lang(self, "cat_desc"))
        self.log = logging.getLogger(__name__)

        self.presence = None
        if Storage.get(self)["state"] == DscState.VOTING:
            self.register_presence()

        self._fill_rule_link()
        Storage().save(self)

    def default_config(self, container=None):
        return {
            'rule_cell': "Aktuell!E2",
            'contestdoc_id': "1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8",
            'winners_range': "Hall of Fame!B4:D200",
            'channel_id': 0,
            'mod_role_id': 0
        }

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
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
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

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

    async def build_info_embed(self, rules: bool = False, songmasters: bool = False) -> Embed:
        """
        Builds an embed with stored dsc info.

        :param rules: Flag to include the rules link
        :param songmasters: Flag to include a list of songmasters
        :return: Embed with info
        :raises ConfigError: If a config key is missing
        """
        date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y, %H:%M'))
        if not Storage.get(self)['host_id']:
            raise ConfigError('must_set_host')

        host_nick = get_best_user(Storage.get(self)['host_id'])

        embed = Embed()
        embed.add_field(name=Lang.lang(self, 'current_host'), value=host_nick.mention)
        if Storage.get(self)['status']:
            embed.description = Storage.get(self)['status']

        if Storage.get(self)['state'] == DscState.SIGN_UP:
            date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y')) \
                if Storage.get(self)['date'] > datetime.now() \
                else ""
            embed.title = Lang.lang(self, 'signup_phase_info', date_out_str)
            embed.add_field(name=Lang.lang(self, 'sign_up'), value=self._get_doc_link())

        elif Storage.get(self)['state'] == DscState.VOTING:
            embed.title = Lang.lang(self, 'voting_phase_info', date_out_str)
            embed.add_field(name=Lang.lang(self, 'all_songs'), value=self._get_doc_link())
            embed.add_field(name=Lang.lang(self, 'yt_playlist'), value=Storage.get(self)['yt_link'])
            embed.add_field(name=Lang.lang(self, 'points'), value=Storage.get(self)['points'])

        else:
            raise ConfigError(self, 'config_error_reset')

        if rules:
            self._fill_rule_link()
            embed.add_field(name=Lang.lang(self, 'title_rules'), value=f"<{Storage.get(self)['rule_link']}>")

        if songmasters:
            role = Config().bot.guild.get_role(Config().get(self).get("mod_role_id", 0))
            if role:
                s = ", ".join([el.mention for el in role.members])
            else:
                s = "Role not found"
            embed.add_field(name=Lang.lang(self, 'title_songmasters'), value=s)

        return embed

    @commands.group(name="dsc", invoke_without_command=True)
    async def cmd_dsc(self, ctx):
        try:
            embed = await self.build_info_embed()
            await ctx.send(embed=embed)
        except ConfigError as e:
            await ctx.send(Lang.lang(self, e.lang_key))

    @cmd_dsc.command(name="info")
    async def cmd_dsc_info(self, ctx):
        try:
            embed = await self.build_info_embed(rules=True, songmasters=True)
            await ctx.send(embed=embed)
        except ConfigError as e:
            await ctx.send(Lang.lang(self, e.lang_key))

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
        async with ctx.typing():
            c = self.get_api_client()
            winners = c.get(Config.get(self)['winners_range'])

        regex = re.compile(r"\d+")
        w_table = [[Lang.lang(self, 'winner_msg_no'),
                    Lang.lang(self, 'winner_msg_winner'),
                    Lang.lang(self, 'winner_msg_pts'),
                    Lang.lang(self, 'winner_msg_max'),
                    Lang.lang(self, 'winner_msg_pts_perc'),
                    Lang.lang(self, 'winner_msg_participants'),
                    Lang.lang(self, 'winner_msg_month')]]
        for w in winners[1:]:
            if w[0] is None or not w[0]:
                continue

            m0 = regex.findall(w[0])
            m2 = regex.findall(w[2])
            no = m0[0]
            year = int(m0[2])
            month = int(m0[1])
            participator_coutn = m0[3]
            winner_name = w[1]
            pts_winner = int(m2[0])
            pts_max = int(m2[1])
            pts_percentage = round(pts_winner / pts_max * 100)

            w_table.append([no, winner_name, pts_winner, pts_max, f"{pts_percentage:>3} %",
                            participator_coutn, f"{month:>2}/{year:>2}"])

        table_msg = table(w_table, True, prefix="", suffix="")
        values = list(paginate(table_msg.split("\n"), msg_prefix="```", msg_suffix="```", threshold=900))
        embed = Embed(title=Lang.lang(self, 'winner_prefix'))
        prev_last = 0
        for i in range(len(values)):
            line_cnt = values[i].count("\n") + 1  # assuming, paginate doesn't add a \n char at the last line
            if i == 0:
                line_cnt -= 2
            last = prev_last + line_cnt
            embed.add_field(name=f"#{prev_last + 1} - #{last}", value=values[i], inline=False)
            prev_last = last
        await ctx.send(embed=embed)

    @cmd_dsc.group(name="set", invoke_without_command=True)
    @_dsc_set_checks()
    async def cmd_dsc_set(self, ctx, *args):
        if len(args) > 2 and args[1] == "until":
            # !dsc set <signup|voting> until <date>
            await ctx.invoke(self.bot.get_command('dsc set state'), args[0])
            await ctx.invoke(self.bot.get_command('dsc set date'), args[2:])

        elif ctx.invoked_subcommand is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd_dsc_set.command(name="host")
    async def cmd_dsc_set_host(self, ctx, user: Union[Member, User]):
        Storage.get(self)['host_id'] = user.id
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _dsc_save_state(self, ctx, new_state: DscState):
        Storage.get(self)['state'] = new_state
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="state")
    async def cmd_dsc_set_state(self, ctx, state):
        state_re = {
            DscState.VOTING: Lang.lang(self, "phase_names_voting").split(","),
            DscState.SIGN_UP: Lang.lang(self, "phase_names_signup").split(",")
        }

        # parse state arg
        found_state = None
        for s in (DscState.VOTING, DscState.SIGN_UP):
            for el in state_re[s]:
                if el.lower().strip() == state.lower().strip():
                    found_state = s
                    break
            if found_state is not None:
                break

        if found_state is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "invalid_phase"))
            return

        # do stuff
        await self._dsc_save_state(ctx, found_state)
        if found_state == DscState.VOTING:
            self.register_presence()
        elif found_state == DscState.SIGN_UP:
            self.deregister_presence()

    @cmd_dsc_set.command(name="yt")
    async def cmd_dsc_set_yt_link(self, ctx, link):
        link = clear_link(link)
        Storage.get(self)['yt_link'] = link
        Storage().save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_dsc_set.command(name="date")
    async def cmd_dsc_set_date(self, ctx, *args):
        date = timeutils.parse_time_input(args, end_of_day=True)

        # catch parse error
        if not args and date == datetime.max:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "invalid_datetime", " ".join(args)))
            return

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
            for el in Config.get(self):
                msg.append("{}: {}".format(el, Config.get(self)[el]))
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
            Config.get(self)[key] = role.id

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
