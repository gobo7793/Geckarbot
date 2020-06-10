import discord
from discord.ext import commands
from conf import Config

from Geckarbot import BasePlugin


class Plugin(BasePlugin, name="Funny/Misc Commands"):
    """Sport related commands"""

    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self)

    def default_config(self):
        return {}

    @commands.command(name="dice", brief="Simulates rolling dice.",
                      usage="[NumberOfSides] [NumberOfDices]")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        await ctx.send(', '.join(dice))

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de")
    async def kicker_table(self, ctx):
        """Returns the kicker.de Bundesliga tables"""
        embed = discord.Embed(title=Config().lang(self, 'kicker_title'))
        embed.add_field(name="Bundesliga", value="https://www.kicker.de/1-bundesliga/tabelle")
        embed.add_field(name="2. Bundesliga", value="https://www.kicker.de/2-bundesliga/tabelle")
        embed.add_field(name="3. Liga", value="https://www.kicker.de/3-liga/tabelle")
        embed.add_field(name="AT-Bundesliga", value="https://www.kicker.de/tipp3-bundesliga/tabelle\n"
                                                     "https://www.kicker.de/meistergruppe-oesterreich-fb-1/tabelle/\n"
                                                     "https://www.kicker.de/qualifikationsgruppe-oesterreich-fb-1/tabelle/")
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
    async def nico(self, ctx):
        await ctx.send(Config().lang(self, 'nico_output'))

    @commands.command(name="mimimi", help="Provides an .mp3 file that plays the sound of 'mimimi'.")
    async def mimimi(self, ctx):
        await ctx.trigger_typing()
        file = discord.File(f"{Config().storage_dir(self)}/mimimi.mp3")
        await ctx.send(file=file)

    @commands.command(name="geck", help="GECKARBOR!")
    async def geck(self, ctx):
        await ctx.trigger_typing()
        file = discord.File(f"{Config().storage_dir(self)}/treeckos.png")
        await ctx.send("arbor!", file=file)

    @commands.command(name="liebe", help="Provides love to the channel")
    async def liebe(self, ctx):
        await ctx.send("https://www.youtube.com/watch?v=TfmJPDmaQdg")
