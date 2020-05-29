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
        if ctx.invoked_subcommand is None:
            await self.getInfo(ctx)

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def getRules(self, ctx):
        await ctx.send(config.dsc['rule_link'])

    @dsc.command(name="info", help="Get informations about current DSC")
    async def getInfo(self, ctx):
        if config.dsc['state'] == DscState.Registration:
            await ctx.send(":clipboard: **Anmeldung offen!**\n"
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

    @dsc.group(name="set", help="Set data about current DSC", usage="<hoster|state|votingend|yt>", pass_context=True)
    async def setInfo(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !dsc set <host|state|yt|votingend>")

    # Why is this working only without self?!?!?!
    @setInfo.command(name="host", help="Sets the current DSC hoster", usage="<user>")
    async def setHost(self, ctx, user:discord.Member):
        config.dsc['hostId'] = user.id
        self._writeDscFile()
        await ctx.send("New hoster set.")

    @setInfo.command(name="state", help="Sets the current DSC state (Voting/Registration)", usage="<voting|registration>")
    async def setState(self, ctx, state:str):
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
    async def setYtLink(self, ctx, link):
        config.dsc['yt_playlist_link'] = link
        self._writeDscFile()
        await ctx.send("New Youtube playlist link set.")

    @setInfo.command(name="votingend", help="Sets the voting end date", usage="DD.MM.JJJJ HH:MM")
    async def setVotingEnd(self, ctx, *, dateStr):
        config.dsc['voting_end'] = datetime.strptime(dateStr,"%d.%m.%Y %H:%M")
        self._writeDscFile()
        await ctx.send("New voting end date set.")
