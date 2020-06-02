import discord
from discord.ext import commands

import Geckarbot


class gettingCommands(commands.Cog, name="Simple message or data return Commands"):
    """Sport related commands"""

    def __init__(self, bot):
        self.bot = bot
        print("Instantiating")
        super().__init__()

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de")
    async def kicker_table(self, ctx):
        """Returns the kicker.de Bundesliga tables"""
        embed = discord.Embed(title='Kicker.de-Tabellenlinks')
        embed.add_field(name="Bundesliga", value="https://www.kicker.de/1-bundesliga/tabelle")
        embed.add_field(name="2. Bundesliga", value="https://www.kicker.de/2-bundesliga/tabelle")
        embed.add_field(name="3. Liga", value="https://www.kicker.de/3-liga/tabelle")
        embed.add_field(name="AT-Bundesliga", value="https://www.kicker.de/tipp3-bundesliga/tabelle")
        await ctx.send(embed=embed)

    @commands.command(name="ping", help="Pings the bot.")
    async def ping(self, ctx):
        await ctx.send("Pong!")
        
    @commands.command(name="mud", brief="Pings the bot.")
    async def mud(self, ctx):
        await ctx.send("Kip!")
        
    @commands.command(name="mudkip", brief="MUDKIP!")
    async def mudkip(self, ctx):
        await ctx.send("https://www.youtube.com/watch?v=3DkqMjfqqPc")

    @commands.command(name="nico", help="Punches Nico.")
    async def ping(self, ctx):
        await ctx.send("***N I C O   A U F S   M A U L !***   :right_facing_fist_tone1::cow:")


class Plugin(Geckarbot.Plugin):
    def __init__(self, bot):
        self.register(gettingCommands)
