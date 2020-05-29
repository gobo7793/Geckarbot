import os
import json
import discord

from datetime import datetime
from discord.ext import commands

import botUtils
from config import config
from botUtils import jsonUtils
from botUtils.enums import DscState

# Workaround for working with !dsc set commands


class dscCommands(commands.Cog, name="DSC Commands"):
    """Commands for DSC"""

    def __init__(self, bot):
        self.bot = bot
        self._readDscFile()

    def _readDscFile(self):
        """Reads the dsc config file"""
        if os.path.exists(config.dsc_file):
            with open(config.dsc_file, "r") as f:
                try:
                    config.dsc = json.load(f, object_hook=jsonUtils.decoder_obj_hook)
                except:
                    pass

    def _writeDscFile(self):
        """Writes the dsc config file"""
        with open(config.dsc_file, "w") as f:
            json.dump(config.dsc, f, cls=jsonUtils.Encoder)

    @commands.group(name="dsc", help="Get and manage informations about current DSC",
                    description="Get the informations about the current dsc or manage it. Manage DSC informations is only permitted for songmasters.")
    async def dsc(self, ctx):
        """Basic DSC cmd, if no subcmd given, use info"""
        if ctx.invoked_subcommand is None:
            await self.getInfo(ctx)

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def getRules(self, ctx):
        """Returns the DSC rules"""
        await ctx.send(config.dsc['rule_link'])

    @dsc.command(name="info", help="Get informations about current DSC")
    async def getInfo(self, ctx):
        """Returns basic infos about next/current DSC"""
        if config.dsc['state'] == DscState.Registration:
            await ctx.send(f":clipboard: **Anmeldung offen bis {config.dsc['voting_end'].strftime('%d.%m.%Y')}!**\n"
                        f"Aktueller Ausrichter: {self.bot.get_user(config.dsc['hostId']).name}\n"
                        f"Anmeldung: {config.dsc['contestdoc_link']}")

        elif config.dsc['state'] == DscState.Voting:
            await ctx.send(f":incoming_envelope: **Votingphase läuft bis {config.dsc['voting_end'].strftime('%d.%m.%Y, %H:%M')} Uhr!**\n"
                        f"Votings an: {self.bot.get_user(config.dsc['hostId']).name}\n"
                        f"Alle Songs: {config.dsc['contestdoc_link']}\n"
                        f"Youtube-Playlist: {config.dsc['yt_playlist_link']}")

        else:
            await ctx.send("Configuration error. Please reset dsc configuration.")
            if not config.dsc['hostId'] or not config.dsc['yt_playlist_link']:
                await botUtils.write_debug_channel(self.bot, "DSC config is empty, please reset.")
            else:
                await botUtils.write_debug_channel(self.bot, "Configuration error in DSC config detected. Current configuration:\n"
                        f"Hoster Id: {config.dsc['hostId']}, Username: {self.bot.get_user(config.dsc['hostId']).name}\n"
                        f"State: {config.dsc['state']}\n"
                        f"YT Playlist: {config.dsc['yt_playlist_link']}\n"
                        f"Voting end: {config.dsc['voting_end']}")

    @dsc.group(name="set", help="Set data about current/next DSC", usage="<hoster|state|stateend|yt>")
    @commands.has_any_role("mod", "songmaster", "botmaster")
    async def setInfo(self, ctx):
        """Basic set subcommand, does nothing"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !dsc set <host|state|yt|stateend>")

    @setInfo.command(name="host", help="Sets the current/next DSC hoster", usage="<user>")
    @commands.has_any_role("mod", "songmaster", "botmaster")
    async def setHost(self, ctx, user:discord.Member):
        """Sets the current/next DSC host"""
        config.dsc['hostId'] = user.id
        self._writeDscFile()
        await ctx.send("New hoster set.")

    @setInfo.command(name="state", help="Sets the current DSC state (Voting/Registration)", usage="<voting|registration>")
    @commands.has_any_role("mod", "songmaster", "botmaster")
    async def setState(self, ctx, state):
        """Sets the current DSC state (registration/voting)"""
        if state.lower() == "voting":
            config.dsc['state'] = DscState.Voting
            await ctx.send("Voting phase set.")
        elif state.lower() == "registration":
            config.dsc['state'] = DscState.Registration
            await ctx.send("Registration phase set.")
        else:
            await ctx.send("Invalid DSC phase.")
        self._writeDscFile()

    @setInfo.command(name="yt", help="Sets the Youtube playlist link", usage="<link>")
    @commands.has_any_role("mod", "songmaster", "botmaster")
    async def setYtLink(self, ctx, link):
        """Sets the youtube playlist link"""
        config.dsc['yt_playlist_link'] = link
        self._writeDscFile()
        await ctx.send("New Youtube playlist link set.")

    @setInfo.command(name="stateend", help="Sets the registration/voting end date", usage="DD.MM.JJJJ[ HH:MM]",
                     description="Sets the end date and time for registration and voting phase. If no time is given, 23:59 will be used.")
    @commands.has_any_role("mod", "songmaster", "botmaster")
    async def setStateEnd(self, ctx, dateStr, timeStr=None):
        """Sets the end date (and time) of the current DSC state"""
        if not timeStr:
            dateStr += " 23:59"
        config.dsc['voting_end'] = datetime.strptime(dateStr,"%d.%m.%Y %H:%M")
        self._writeDscFile()
        await ctx.send("New state end date set.")
