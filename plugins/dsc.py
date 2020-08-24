import re
import logging

import discord
from enum import IntEnum

from datetime import datetime
from discord.ext import commands
from conf import Storage, Lang, Config
from botutils import utils, permchecks, sheetsclient, stringutils
from botutils.stringutils import paginate
from base import BasePlugin


class DscState(IntEnum):
    """DSC states"""
    NA = 0
    Voting = 1
    Sign_up = 2


class Plugin(BasePlugin, name="Discord Song Contest"):
    """Commands for the DSC"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self, category="DSC")
        self.log = logging.getLogger("dsc")

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

    def get_api_client(self):
        """Returns a client to access Google Sheets API for the dsc contestdoc sheet"""
        return sheetsclient.Client(Config.get(self)['contestdoc_id'])
        pass

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

    @commands.group(name="dsc", help="Get and manage data about current/next DSC")
    async def dsc(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('dsc info'))

    @dsc.command(name="rules", help="Get the link to the DSC rules", alias="regeln")
    async def dsc_rules(self, ctx):
        self._fill_rule_link()
        await ctx.send(f"<{Storage.get(self)['rule_link']}>")

    @dsc.command(name="status", help="Get the current status message from the Songmasters about the current/next DSC")
    async def dsc_status(self, ctx):
        if Storage.get(self)['status']:
            status_msg = Lang.lang(self, 'status_base', Storage.get(self)['status'])
        else:
            status_msg = Lang.lang(self, 'status_base', Lang.lang(self, 'status_none'))

        await ctx.send(status_msg)

    @dsc.command(name="winners", help="Returns previous DSC winners")
    async def dsc_winners(self, ctx):
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

    @dsc.command(name="info", help="Get information about current DSC")
    async def dsc_info(self, ctx):
        date_out_str = Lang.lang(self, 'info_date_str', Storage.get(self)['date'].strftime('%d.%m.%Y, %H:%M'))
        if not Storage.get(self)['host_id']:
            await ctx.send(Lang.lang(self, 'must_set_host'))
            return

        host_nick = discord.utils.get(ctx.guild.members, id=Storage.get(self)['host_id']).mention

        embed = discord.Embed()
        embed.add_field(name=Lang.lang(self, 'current_host'), value=host_nick)
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

    @dsc.group(name="set", help="Set data about current/next DSC.")
    async def dsc_set(self, ctx):
        if (not permchecks.check_full_access(ctx.author)
                and Config.get(self)['mod_role_id'] != 0
                and Config.get(self)['mod_role_id'] not in [role.id for role in ctx.author.roles]):
            raise commands.BotMissingAnyRole([*Config().FULL_ACCESS_ROLES, Config.get(self)['mod_role_id']])
        if Config.get(self)['channel_id'] != 0 and Config.get(self)['channel_id'] != ctx.channel.id:
            raise commands.CheckFailure()

        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.dsc_set)

    @dsc_set.command(name="host", help="Sets the current/next DSC host")
    async def dsc_set_host(self, ctx, user: discord.Member):
        Storage.get(self)['host_id'] = user.id
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    async def _dsc_save_state(self, ctx, new_state: DscState):
        Storage.get(self)['state'] = new_state
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="state", help="Sets the current DSC state (Voting/Sign up)",
                     usage="<voting|signup>")
    async def dsc_set_state(self, ctx, state):
        if state.lower() == "voting":
            await self._dsc_save_state(ctx, DscState.Voting)
        elif state.lower() == "signup":
            await self._dsc_save_state(ctx, DscState.Sign_up)
        else:
            await ctx.send(Lang.lang(self, 'invalid_phase'))

    @dsc_set.command(name="yt", help="Sets the Youtube playlist link")
    async def dsc_set_yt_link(self, ctx, link):
        link = stringutils.clear_link(link)
        Storage.get(self)['yt_link'] = link
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="date", help="Sets the registration/voting end date", usage="DD.MM.YYYY [HH:MM]",
                     description="Sets the end date and time for registration and voting phase. "
                                 "If no time is given, 23:59 will be used.")
    async def dsc_set_date(self, ctx, date_str, time_str=None):
        if not time_str:
            time_str = "23:59"
        Storage.get(self)['date'] = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="status", help="Sets the status message",
                     description="Sets a status message for additional information. To remove give no message.")
    async def dsc_set_status(self, ctx, *message):
        Storage.get(self)['status'] = " ".join(message)
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="points", help="Sets the voting system",
                     description="Sets the point list for the current voting system. Points can be set like "
                                 "\"12-10-...\" or \"12 10 ...\", which will be converted to the first.")
    async def dsc_set_status(self, ctx, *points):
        Storage.get(self)['points'] = "-".join(points)
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="config", invoke_without_command=True,
                     help="Gets or sets general config values for the plugin")
    async def dsc_set_config(self, ctx, key="", value=""):
        if not key and not value:
            await ctx.invoke(self.bot.get_command("configdump"), self.get_name())
            return

        if key and not value:
            key_value = Config.get(self).get(key, None)
            if key_value is None:
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'key_not_exist', key))
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
                Lang.lang(self, 'songmaster_id')
                await ctx.message.add_reaction(Lang.CMDERROR)
                return
            else:
                Config.get(self)[key] = int_value

        else:
            Config.get(self)[key] = value

        Config.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
