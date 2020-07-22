import re

import discord
from enum import IntEnum

from datetime import datetime
from discord.ext import commands
from conf import Config
from botutils import utils, permChecks, sheetsclient
from Geckarbot import BasePlugin


lang = {
    'en': {
        'status_base': "Important message from the Songmasters: {}",
        'status_none': "Have fun and love Treecko, Mudkip and Oshawott!",
        'must_set_host': "You must set DSC host!",
        'info_date_str': " until {}",
        'signup_phase_info': ":clipboard: Signing up open{}!",
        'current_host': "Current Host",
        'sign_up': "Sign up",
        'voting_phase_info': ":incoming_envelope: Voting is open{}",
        'votings_to': "Votings to",
        'all_songs': "All songs",
        'yt_playlist': "Youtube playlist",
        'config_error_reset': "Configuration error. Please reset dsc configuration.",
        'config_error': "DSC configuration error, config values:",
        'new_host_set': "New host set.",
        'phase_set': "{} state set.",
        'invalid_phase': "Invalid dsc state.",
        'yt_link_set': "New Youtube playlist link set.",
        'state_end_set': "New state end date set.",
        'status_set': "New status message set.",
        'winner_prefix': "**Previous DSC winners:**\n",
        'winner_msg': "**#{}**: {} with {}/{} Points ({} %, {} TN in {}/{})",
        }
    }


class DscState(IntEnum):
    """DSC states"""
    NA = 0
    Voting = 1
    Sign_up = 2


class Plugin(BasePlugin, name="Discord Song Contest"):
    """Commands for the DSC"""

    songmaster_role_id = 0

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.dsc_conf()['rule_link'] = self._get_rule_link()
        Config().save(self)

    def default_config(self):
        return {
            'rule_cell': "Aktuell!F2",
            'rule_link': None,
            'contestdoc_id': "1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8",
            'winners_range': "Hall of Fame!B4:D200",
            'host_id': None,
            'state': DscState.NA,
            'yt_link': None,
            'state_end': datetime.now(),
            'status': None
        }

    def get_lang(self):
        return lang

    def dsc_conf(self):
        return Config().get(self)

    def dsc_lang(self, str_name, *args):
        return Config().lang(self, str_name, *args)

    def get_api_client(self):
        """Returns a client to access Google Sheets API for the dsc contestdoc sheet"""
        return sheetsclient.Client(self.dsc_conf()['contestdoc_id'])

    def _get_doc_link(self):
        return "https://docs.google.com/spreadsheets/d/{}".format(self.dsc_conf()['contestdoc_id'])

    def _get_rule_link(self):
        c = self.get_api_client()
        values = c.get(self.dsc_conf()['rule_cell'])
        return values[0][0]

    @commands.group(name="dsc", invoke_without_command=True, help="Get and manage informations about current DSC",
                    description="Get the informations about the current dsc or manage it. "
                                "Command only works in music channel. "
                                "Manage DSC informations is only permitted for songmasters.")
    @permChecks.in_channel(Config().CHAN_IDS.get('music', 0))
    async def dsc(self, ctx):
        await ctx.invoke(self.bot.get_command('dsc info'))

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def dsc_rules(self, ctx):
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
        regex = re.compile("\d+")
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

            w_msgs.append(Config().lang(self, 'winner_msg', no, winner_name, pts_winner, pts_max, pts_percentage,
                                        participator_coutn, dt.month, dt.year))

        for m in utils.paginate(w_msgs, Config().lang(self, 'winner_prefix')):
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

    @dsc.group(name="set", invoke_without_command=True, usage="<host|state|stateend|status|yt>",
               help="Set data about current/next DSC.")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID, Config().ROLE_IDS.get('songmaster', 0))
    async def dsc_set(self, ctx):
        await ctx.send_help(self.dsc_set)

    @dsc_set.command(name="host", help="Sets the current/next DSC hoster", usage="<user>")
    async def dsc_set_host(self, ctx, user: discord.Member):
        self.dsc_conf()['host_id'] = user.id
        Config().save(self)
        # await ctx.send(self.dsc_lang('new_host_set'))
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    async def dsc_save_state(self, ctx, new_state: DscState):
        self.dsc_conf()['state'] = new_state
        # state_str = str(DscState(self.dsc_conf()['state']))
        # state_str = state_str[state_str.find(".") + 1:].replace("_", " ")
        Config().save(self)
        # await ctx.send(self.dsc_lang('phase_set', state_str))
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    @dsc_set.command(name="state", help="Sets the current DSC state (Voting/Sign up)",
                     usage="<voting|signup>")
    async def dsc_set_state(self, ctx, state):
        if state.lower() == "voting":
            await self.dsc_save_state(ctx, DscState.Voting)
        elif state.lower() == "signup":
            await self.dsc_save_state(ctx, DscState.Sign_up)
        else:
            await ctx.send(self.dsc_lang('invalid_phase'))

    @dsc_set.command(name="yt", help="Sets the Youtube playlist link", usage="<link>")
    async def dsc_set_yt_link(self, ctx, link):
        link = utils.clear_link(link)
        self.dsc_conf()['yt_link'] = link
        Config().save(self)
        # await ctx.send(self.dsc_lang('yt_link_set'))
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    @dsc_set.command(name="date", help="Sets the registration/voting end date", usage="DD.MM.YYYY [HH:MM]",
                     description="Sets the end date and time for registration and voting phase. "
                                 "If no time is given, 23:59 will be used.")
    async def dsc_set_date(self, ctx, date_str, time_str=None):
        if not time_str:
            time_str = "23:59"
        self.dsc_conf()['state_end'] = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        Config().save(self)
        # await ctx.send(self.dsc_lang('state_end_set'))
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    @dsc_set.command(name="status", help="Sets the status message", usage="[message]",
                     description="Sets a status message for additional informations. To remove give no message.")
    async def dsc_set_status(self, ctx, *status_message):
        self.dsc_conf()['status'] = " ".join(status_message)
        Config().save(self)
        # await ctx.send(self.dsc_lang('status_set'))
        await ctx.message.add_reaction(Config().CMDSUCCESS)
