import random
import discord

from datetime import datetime
from discord.ext import commands
from conf import Config
from botutils import utils, permChecks
from botutils.enums import DscState


class Plugin(commands.Cog, name="Funny/Misc Commands"):
    """Funny and miscellaneous commands without other category"""

    songmaster_role_id = 0

    def __init__(self, bot):
        self.bot = bot
        super(commands.Cog).__init__()
        bot.register(self)

        self.load_def_config()

        global songmaster_role_id
        songmaster_role_id = Config().ROLE_IDS.get('songmaster', 0)

    def dsc_conf(self):
        return Config().get(self)['dsc']

    def load_def_config(self):
        Config().get(self)['dsc'] = Config().get(self).get('dsc', {})

        self.dsc_conf()['rule_link'] = self.dsc_conf().get('rule_link', "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg")
        self.dsc_conf()['contestdoc_link'] = self.dsc_conf().get('contestdoc_link', "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8")
        self.dsc_conf()['host_id'] = self.dsc_conf().get('host_id')
        self.dsc_conf()['state'] = self.dsc_conf().get('state', DscState.NA)
        self.dsc_conf()['yt_link'] = self.dsc_conf().get('yt_link')
        self.dsc_conf()['state_end'] = self.dsc_conf().get('state_end', datetime.now())


    ######
    # Simple games
    ######

    @commands.command(name="dice", brief="Simulates rolling dice.",
                      usage="[NumberOfSides] [NumberOfDices]")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        await ctx.send(', '.join(dice))

    ######
    # DSC
    ######

    @commands.group(name="dsc", help="Get and manage informations about current DSC",
                    description="Get the informations about the current dsc or manage it. "
                                "Command only works in music channel. "
                                "Manage DSC informations is only permitted for songmasters.")
    @permChecks.in_channel(Config().CHAN_IDS.get('music', 0))
    async def dsc(self, ctx):
        """DSC base command, return info command if no subcommand given"""
        if ctx.invoked_subcommand is None:
            await self.dsc_get_info(ctx)

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def dsc_get_rules(self, ctx):
        """Returns the DSC rules"""
        await ctx.send(f"<{self.dsc_conf()['rule_link']}>")

    @dsc.command(name="info", help="Get informations about current DSC")
    async def dsc_get_info(self, ctx):
        """Returns basic infos about next/current DSC"""
        hostNick = None
        dateOutStr = ""
        if not self.dsc_conf()['host_id']:
            await ctx.send("You must set DSC host!")
        else:
            hostNick = discord.utils.get(ctx.guild.members, id=self.dsc_conf()['host_id']).name

        if self.dsc_conf()['state'] == DscState.Registration:
            if self.dsc_conf()['state_end'] > datetime.now():
                dateOutStr = f" bis {self.dsc_conf()['state_end'].strftime('%d.%m.%Y')}"

            embed = discord.Embed(title=f":clipboard: Anmeldung offen{dateOutStr}!")
            embed.add_field(name="Aktueller Ausrichter", value=hostNick)
            embed.add_field(name="Anmeldung", value=self.dsc_conf()['contestdoc_link'])
            await ctx.send(embed=embed)

        elif self.dsc_conf()['state'] == DscState.Voting:
            if self.dsc_conf()['state_end'] > datetime.now():
                dateOutStr = f" bis {self.dsc_conf()['state_end'].strftime('%d.%m.%Y, %H:%M')} Uhr"

            embed = discord.Embed(title=f":incoming_envelope: Votingphase läuft{dateOutStr}!")
            embed.add_field(name="Votings an", value=hostNick)
            embed.add_field(name="Alle Songs", value=self.dsc_conf()['contestdoc_link'])
            embed.add_field(name="Youtube-Playlist", value=self.dsc_conf()['yt_link'])
            await ctx.send(embed=embed)

        else:
            await ctx.send("Configuration error. Please reset dsc configuration.")
            embed = discord.Embed(title="DSC configuration error")
            embed.add_field(name="Host ID", value=str(self.dsc_conf()['host_id']))
            embed.add_field(name="Host Name", value=hostNick)
            embed.add_field(name="State", value=str(self.dsc_conf()['state']))
            embed.add_field(name="YT Playlist", value=str(self.dsc_conf()['yt_link']))
            embed.add_field(name="State End", value=str(self.dsc_conf()['state_end']))
            await utils.write_debug_channel_embed(self.bot, embed)

    @dsc.group(name="set", help="Set data about current/next DSC", usage="<host|state|stateend|yt>")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID, songmaster_role_id)
    async def dsc_set(self, ctx):
        """Basic set subcommand, does nothing"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !dsc set <host|state|yt|stateend>")

    @dsc_set.command(name="host", help="Sets the current/next DSC hoster", usage="<user>")
    #@commands.has_any_role("mod", "songmaster", "botmaster")
    async def dsc_set_host(self, ctx, user: discord.Member):
        """Sets the current/next DSC host"""
        self.dsc_conf()['host_id'] = user.id
        Config().save(self)
        await ctx.send("New hoster set.")

    @dsc_set.command(name="state", help="Sets the current DSC state (Voting/Registration)",
                     usage="<voting|registration>")
    #@commands.has_any_role("mod", "songmaster", "botmaster")
    async def dsc_set_state(self, ctx, state):
        """Sets the current DSC state (registration/voting)"""
        if state.lower() == "voting":
            self.dsc_conf()['state'] = DscState.Voting
            await ctx.send("Voting phase set.")
        elif state.lower() == "registration":
            self.dsc_conf()['state'] = DscState.Registration
            await ctx.send("Registration phase set.")
        else:
            await ctx.send("Invalid DSC phase.")
        Config().save(self)

    @dsc_set.command(name="yt", help="Sets the Youtube playlist link", usage="<link>")
    #@commands.has_any_role("mod", "songmaster", "botmaster")
    async def dsc_set_yt_link(self, ctx, link):
        """Sets the youtube playlist link"""
        link = utils.clear_link(link)
        self.dsc_conf()['yt_link'] = link
        Config().save(self)
        await ctx.send("New Youtube playlist link set.")

    @dsc_set.command(name="stateend", help="Sets the registration/voting end date", usage="DD.MM.JJJJ[ HH:MM]",
                     description="Sets the end date and time for registration and voting phase. "
                                 "If no time is given, 23:59 will be used.")
    #@commands.has_any_role("mod", "songmaster", "botmaster")
    async def dsc_set_state_end(self, ctx, dateStr, timeStr=None):
        """Sets the end date (and time) of the current DSC state"""
        if not timeStr:
            dateStr += " 23:59"
        self.dsc_conf()['state_end'] = datetime.strptime(dateStr,"%d.%m.%Y %H:%M")
        Config().save(self)
        await ctx.send("New state end date set.")
