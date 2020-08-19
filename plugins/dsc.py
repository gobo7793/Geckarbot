import re
import logging

import discord
from enum import IntEnum

from datetime import datetime
from discord.ext import commands
from conf import Storage, Lang, Config
from botutils import utils, permChecks, sheetsclient
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
        bot.register(self)
        self.log = logging.getLogger("dsc")

        self.dsc_conf()['rule_link'] = self._get_rule_link()
        Storage().save(self)

    def default_storage(self):
        return {
            'rule_cell': "Aktuell!E2",
            'rule_link': None,
            'contestdoc_id': "1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8",
            'winners_range': "Hall of Fame!B4:D200",
            'host_id': None,
            'state': DscState.NA,
            'yt_link': None,
            'points': "",
            'state_end': datetime.now(),
            'status': None
        }

    def get_lang(self):
        return lang

    def dsc_conf(self):
        return Storage().get(self)

    def dsc_lang(self, str_name, *args):
        return Lang.lang(self, str_name, *args)

    def get_api_client(self):
        """Returns a client to access Google Sheets API for the dsc contestdoc sheet"""
        return sheetsclient.Client(self.dsc_conf()['contestdoc_id'])

    def _get_doc_link(self):
        return "https://docs.google.com/spreadsheets/d/{}".format(self.dsc_conf()['contestdoc_id'])

    def _get_rule_link(self):
        try:
            c = self.get_api_client()
            values = c.get(self.dsc_conf()['rule_cell'])
            return values[0][0]
        except IndexError:
            self.log.error("Can't read rules link from Contestdoc sheet. "
                           "Is Google Sheets not reachable or do you set the wrong cell?")
            return ""

    @commands.group(name="dsc", help="Get and manage data about current/next DSC")
    async def dsc(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('dsc info'))

    @dsc.command(name="rules", help="Get the link to the DSC rules", alias="regeln")
    async def dsc_rules(self, ctx):
        if not self.dsc_conf()['rule_link']:
            self._get_rule_link()
        await ctx.send(f"<{self.dsc_conf()['rule_link']}>")

    @dsc.command(name="status", help="Get the current informations from the Songmasters about the current/next DSC")
    async def dsc_status(self, ctx):
        if self.dsc_conf()['status']:
            status_msg = self.dsc_lang('status_base', self.dsc_conf()['status'])
        else:
            status_msg = self.dsc_lang('status_base', self.dsc_lang('status_none'))

        await ctx.send(status_msg)

    @dsc.command(name="winners", help="Returns previous DSC winners")
    async def dsc_winners(self, ctx):
        c = self.get_api_client()
        winners = c.get(self.dsc_conf()['winners_range'])

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

        for m in utils.paginate(w_msgs, Lang.lang(self, 'winner_prefix')):
            await ctx.send(m)

    @dsc.command(name="info", help="Get informations about current DSC")
    async def dsc_info(self, ctx):
        host_nick = None
        date_out_str = self.dsc_lang('info_date_str', self.dsc_conf()['state_end'].strftime('%d.%m.%Y, %H:%M'))
        if not self.dsc_conf()['host_id']:
            await ctx.send(self.dsc_lang('must_set_host'))
        else:
            host_nick = discord.utils.get(ctx.guild.members, id=self.dsc_conf()['host_id']).mention

        if self.dsc_conf()['state'] == DscState.Sign_up:
            if self.dsc_conf()['state_end'] > datetime.now():
                date_out_str = self.dsc_lang('info_date_str', self.dsc_conf()['state_end'].strftime('%d.%m.%Y'))
            else:
                date_out_str = ""

            embed = discord.Embed(title=self.dsc_lang('signup_phase_info', date_out_str))
            embed.add_field(name=self.dsc_lang('current_host'), value=host_nick)
            embed.add_field(name=self.dsc_lang('sign_up'), value=self._get_doc_link())
            if self.dsc_conf()['status']:
                embed.description = self.dsc_conf()['status']
            await ctx.send(embed=embed)

        elif self.dsc_conf()['state'] == DscState.Voting:
            embed = discord.Embed(title=self.dsc_lang('voting_phase_info', date_out_str))
            embed.add_field(name=self.dsc_lang('current_host'), value=host_nick)
            embed.add_field(name=self.dsc_lang('all_songs'), value=self._get_doc_link())
            embed.add_field(name=self.dsc_lang('yt_playlist'), value=self.dsc_conf()['yt_link'])
            embed.add_field(name=self.dsc_lang('points'), value=self.dsc_conf()['points'])
            if self.dsc_conf()['status']:
                embed.description = self.dsc_conf()['status']
            await ctx.send(embed=embed)

        else:
            await ctx.send(self.dsc_lang('config_error_reset'))
            embed = discord.Embed(title=self.dsc_lang('config_error'))
            embed.add_field(name="Host ID", value=str(self.dsc_conf()['host_id']))
            embed.add_field(name="Host Nick", value=host_nick)
            embed.add_field(name="State", value=str(self.dsc_conf()['state']))
            embed.add_field(name="YT Link", value=str(self.dsc_conf()['yt_link']))
            embed.add_field(name="State End", value=str(self.dsc_conf()['state_end']))
            embed.add_field(name="Status", value=str(self.dsc_conf()['status']))
            await utils.write_debug_channel(self.bot, embed)

    @dsc.group(name="set", help="Set data about current/next DSC.")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES, Config().ROLE_IDS.get('songmaster', 0))
    @permChecks.in_channel(Config().CHAN_IDS.get('music', 0))
    async def dsc_set(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.dsc_set)

    @dsc_set.command(name="host", help="Sets the current/next DSC host")
    async def dsc_set_host(self, ctx, user: discord.Member):
        self.dsc_conf()['host_id'] = user.id
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    async def _dsc_save_state(self, ctx, new_state: DscState):
        self.dsc_conf()['state'] = new_state
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
            await ctx.send(self.dsc_lang('invalid_phase'))

    @dsc_set.command(name="yt", help="Sets the Youtube playlist link")
    async def dsc_set_yt_link(self, ctx, link):
        link = utils.clear_link(link)
        self.dsc_conf()['yt_link'] = link
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="date", help="Sets the registration/voting end date", usage="DD.MM.YYYY [HH:MM]",
                     description="Sets the end date and time for registration and voting phase. "
                                 "If no time is given, 23:59 will be used.")
    async def dsc_set_date(self, ctx, date_str, time_str=None):
        if not time_str:
            time_str = "23:59"
        self.dsc_conf()['state_end'] = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="status", help="Sets the status message",
                     description="Sets a status message for additional information. To remove give no message.")
    async def dsc_set_status(self, ctx, *message):
        self.dsc_conf()['status'] = " ".join(message)
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @dsc_set.command(name="points", help="Sets the voting system",
                     description="Sets the point list for the current voting system. Points can be set like "
                                 "\"12-10-...\" or \"12 10 ...\", which will be converted to the first.")
    async def dsc_set_status(self, ctx, *points):
        self.dsc_conf()['points'] = "-".join(points)
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
