import os
import discord

from datetime import datetime
from discord.ext import commands

from config import config
from botUtils import writeChannels
from botUtils.enums import DscState

class dscCommands(commands.Cog, name="DSC Commands"):
    """Commands for DSC"""

    def __init__(self, bot):
        self.bot = bot
        self._readDscFile()

    def _writeDscFile(self):
        """Writes the dsc config file"""
        with open(config.dsc_file, "w") as f:
            json.dump(config.dsc, f)

    def _readDscFile(self):
        """Reads the dsc config file"""
        if os.path.exists(config.dsc_file):
            with open(config.dsc, "r") as f:
                try:
                    config.dsc = json.load(f)
                except:
                    pass

    @commands.group(name="dsc", help="Get and manage informations about current DSC",
                    description="Get the informations about the current dsc or manage it. Manage DSC informations is only permitted for songmasters.")
    async def dsc(self, ctx):
        if ctx.invoked_subcommand is None:
            print("dsc")
            await self.getDscInfo(ctx)

    @dsc.command(name="rules", help="Get the link to the DSC rules")
    async def dscRules(self, ctx):
        await ctx.send(config.dsc['rule_link'])

    @dsc.command(name="info", help="Get informations about current DSC")
    async def getDscInfo(self, ctx):
        if config.dsc['state'] == DscState.Registration:
            await ctx.send(":clipboard: *Anmeldung offen!*\n"
                        f"Aktueller Ausrichter: {self.bot.get_user(config.dsc['hostId'])}\n"
                        f"Anmeldung: {config.dsc['contestdoc_link']}")
        elif config.dsc['state'] == DscState.Voting:
            await ctx.send(":incoming_envelope: *Votingphase läuft bis {config.dsc['voting_end'].strftime(%d.%m.%Y, %H:%M)} Uhr!*\n"
                        f"Votings an: {self.bot.get_user(config.dsc['hostId'])}\n"
                        f"Alle Songs: {config.dsc['contestdoc_link']}\n"
                        f"Youtube-Playlist: {config.dsc['yt_playlist_link']}")
        else:
            await ctx.send("Configuration error. Please reset dsc configuration.")
            if not config.dsc['hostId'] or not config.dsc['yt_playlist_link']:
                await writeChannels.write_debug_channel(self.bot, "DSC config is empty, please reset.")
            else:
                await writeChannels.write_debug_channel(self.bot, "Configuration error in DSC config detected. Current configuration:\n"
                        f"Hoster Id: {config.dsc['hostId']}, Username: {self.bot.get_user(config.dsc['hostId']).name}\n"
                        f"State: {config.dsc['state']}\n"
                        f"YT Playlist: {config.dsc['yt_playlist_link']}\n"
                        f"Voting end: {config.dsc['voting_end']}")

    @dsc.group(name="set", help="Set data about current DSC", usage="<hoster|state|votingend|yt>", pass_context=True)
    async def setDscInfo(self, ctx):
        if ctx.invoked_subcommand is None:
            print("dsc set")
            await ctx.send("Usage: !dsc set <hoster|state|votingend|yt>")

    @setDscInfo.command(name="hoster", help="Sets the current DSC hoster", usage="<user>")
    async def setDscHoster(self, ctx, user:discord.Member):
        config.dsc['hostId'] = user.id
        await ctx.send("New hoster set.")

    @setDscInfo.command(name="state", help="Sets the current DSC state (Voting/Registration)", usage="<voting|registration>")
    async def setDscHoster(self, ctx, state):
        if state == "voting":
            config.dsc['state'] = DscState.Voting
            await ctx.send("Voting phase set.")
        elif state == "registration":
            config.dsc['state'] = DscState.Registration
            await ctx.send("Registration phase set.")
        else:
            await ctx.send("Invalid DSC phase.")

    @setDscInfo.command(name="yt", help="Sets the Youtube playlist link", usage="<link>")
    async def setDscHoster(self, ctx, link):
        config.dsc['yt_playlist_link'] = link
        await ctx.send("New Youtube playlist link set.")

    @setDscInfo.command(name="votingend", help="Sets the voting end date", usage="DD.MM.JJJJ HH:MM")
    async def setDscHoster(self, ctx, dateStr):
        config.dsc['voting_end'] = datetime.strptime(dateStr,"%d.%m.%Y, %H:%M")
        await ctx.send("New voting end date set.")
