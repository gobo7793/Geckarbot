import discord

from datetime import datetime
from discord.ext import commands
from conf import Config
from botutils import utils, permChecks
from botutils.enums import DscState
from Geckarbot import BasePlugin


class Plugin(BasePlugin, name="Discord Song Contest"):
    """Commands for the DSC"""

    songmaster_role_id = 0

    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self)

        global songmaster_role_id
        songmaster_role_id = Config().ROLE_IDS.get('songmaster', 0)

    def default_config(self):
        return {
            'rule_link': "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg",
            'contestdoc_link': "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8",
            'host_id': None,
            'state': DscState.NA,
            'yt_link': None,
            'state_end': datetime.now(),
            'status': None
        }

    def dsc_conf(self):
        return Config().get(self)

    def dsc_lang(self, str_name, *args):
        return Config().lang(self, str_name, *args)


    @commands.group(name="dsc", help="Get and manage informations about current DSC",
                    description="Get the informations about the current dsc or manage it. "
                                "Command only works in music channel. "
                                "Manage DSC informations is only permitted for songmasters.")
    @permChecks.in_channel(Config().CHAN_IDS.get('music', 0))
    async def dsc(self, ctx):
        """DSC base command, return info command if no subcommand given"""
        if ctx.invoked_subcommand is None:
            await self.dsc_info(ctx)

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def dsc_rules(self, ctx):
        """Returns the DSC rules"""
        await ctx.send(f"<{self.dsc_conf()['rule_link']}>")

    @dsc.command(name="status", help="Get the current informations from the Songmasters about the current/next DSC")
    async def dsc_status(self, ctx):
        """Returns the DSC status message"""
        if self.dsc_conf()['status']:
            status_msg = self.dsc_lang('status_base', self.dsc_conf()['status'])
        else:
            status_msg = self.dsc_lang('status_base', self.dsc_lang('status_none'))

        await ctx.send(status_msg)

    @dsc.command(name="info", help="Get informations about current DSC")
    async def dsc_info(self, ctx):
        """Returns basic infos about next/current DSC"""
        hostNick = None
        dateOutStr = self.dsc_lang('info_date_str', self.dsc_conf()['state_end'].strftime('%d.%m.%Y, %H:%M'))
        if not self.dsc_conf()['host_id']:
            await ctx.send(self.dsc_lang('must_set_host'))
        else:
            hostNick = discord.utils.get(ctx.guild.members, id=self.dsc_conf()['host_id']).mention

        if self.dsc_conf()['state'] == DscState.Sign_up:
            if self.dsc_conf()['state_end'] > datetime.now():
                dateOutStr = self.dsc_lang('info_date_str', self.dsc_conf()['state_end'].strftime('%d.%m.%Y'))
            else:
                dateOutStr = ""

            embed = discord.Embed(title=self.dsc_lang('signup_phase_info', dateOutStr))
            embed.add_field(name=self.dsc_lang('current_host'), value=hostNick)
            embed.add_field(name=self.dsc_lang('sign_up'), value=self.dsc_conf()['contestdoc_link'])
            if self.dsc_conf()['status']:
                embed.description = self.dsc_conf()['status']
            await ctx.send(embed=embed)

        elif self.dsc_conf()['state'] == DscState.Voting:
            embed = discord.Embed(title=self.dsc_lang('voting_phase_info', dateOutStr))
            embed.add_field(name=self.dsc_lang('current_host'), value=hostNick)
            embed.add_field(name=self.dsc_lang('all_songs'), value=self.dsc_conf()['contestdoc_link'])
            embed.add_field(name=self.dsc_lang('yt_playlist'), value=self.dsc_conf()['yt_link'])
            if self.dsc_conf()['status']:
                embed.description = self.dsc_conf()['status']
            await ctx.send(embed=embed)

        else:
            await ctx.send(self.dsc_lang('config_error_reset'))
            embed = discord.Embed(title=self.dsc_lang('config_error'))
            embed.add_field(name="Host ID", value=str(self.dsc_conf()['host_id']))
            embed.add_field(name="Host Nick", value=hostNick)
            embed.add_field(name="State", value=str(self.dsc_conf()['state']))
            embed.add_field(name="YT Link", value=str(self.dsc_conf()['yt_link']))
            embed.add_field(name="State End", value=str(self.dsc_conf()['state_end']))
            embed.add_field(name="Status", value=str(self.dsc_conf()['status']))
            await utils.write_debug_channel(self.bot, embed)

    @dsc.group(name="set", help="Set data about current/next DSC.", usage="<host|state|stateend|status|yt>")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID, songmaster_role_id)
    async def dsc_set(self, ctx):
        """Basic set subcommand, does nothing"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.dsc_set)

    @dsc_set.command(name="host", help="Sets the current/next DSC hoster", usage="<user>")
    async def dsc_set_host(self, ctx, user: discord.Member):
        """Sets the current/next DSC host"""
        self.dsc_conf()['host_id'] = user.id
        Config().save(self)
        await ctx.send(self.dsc_lang('new_host_set'))

    async def dsc_save_state(self, ctx, new_state: DscState):
        """Saves the new DSC state and prints it to user"""
        self.dsc_conf()['state'] = new_state
        state_str = str(DscState(self.dsc_conf()['state']))
        state_str = state_str[state_str.find(".") + 1:].replace("_", " ")
        Config().save(self)
        await ctx.send(self.dsc_lang('phase_set', state_str))
        
    @dsc_set.command(name="state", help="Sets the current DSC state (Voting/Sign up)",
                     usage="<voting|signup>")
    async def dsc_set_state(self, ctx, state):
        """Sets the current DSC state (registration/voting)"""
        if state.lower() == "voting":
            await self.dsc_save_state(ctx, DscState.Voting)
        elif state.lower() == "signup":
            await self.dsc_save_state(ctx, DscState.Sign_up)
        else:
            await ctx.send(self.dsc_lang('invalid_phase'))

    @dsc_set.command(name="yt", help="Sets the Youtube playlist link", usage="<link>")
    async def dsc_set_yt_link(self, ctx, link):
        """Sets the youtube playlist link"""
        link = utils.clear_link(link)
        self.dsc_conf()['yt_link'] = link
        Config().save(self)
        await ctx.send(self.dsc_lang('yt_link_set'))

    @dsc_set.command(name="stateend", help="Sets the registration/voting end date", usage="DD.MM.YYYY [HH:MM]",
                     description="Sets the end date and time for registration and voting phase. "
                                 "If no time is given, 23:59 will be used.")
    async def dsc_set_state_end(self, ctx, dateStr, timeStr=None):
        """Sets the end date (and time) of the current DSC state"""
        if not timeStr:
            timeStr = "23:59"
        self.dsc_conf()['state_end'] = datetime.strptime(f"{dateStr} {timeStr}","%d.%m.%Y %H:%M")
        Config().save(self)
        await ctx.send(self.dsc_lang('state_end_set'))

    @dsc_set.command(name="status", help="Sets the status message", usage="[message]",
                     description="Sets a status message for additional informations. To remove give no message.")
    async def dsc_set_status(self, ctx, *status_message):
        """Sets the dsc status message or removes it if no message is given"""
        self.dsc_conf()['status'] = " ".join(status_message)
        Config().save(self)
        await ctx.send(self.dsc_lang('status_set'))
