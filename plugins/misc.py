import random
import discord
from discord.ext import commands
from conf import Config

from Geckarbot import BasePlugin


class Plugin(BasePlugin, name="Funny/Misc Commands"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)


    @commands.command(name="dice", brief="Simulates rolling dice.",
                      usage="[NumberOfSides] [NumberOfDices]")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        results = ', '.join(dice)
        if len(results) > 2000:
            pos_last_comma = results[:1995].rfind(',')
            results = f"{results[:pos_last_comma + 1]} ..."
        await ctx.send(results)

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de")
    async def kicker_table(self, ctx):
        embed = discord.Embed(title=Config().lang(self, 'kicker_title'))
        embed.add_field(name=Config().lang(self, 'kicker_1BL'), value=Config().lang(self, 'kicker_1BL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_2BL'), value=Config().lang(self, 'kicker_2BL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_3FL'), value=Config().lang(self, 'kicker_3FL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_ATBL'), value=Config().lang(self, 'kicker_ATBL_link'))
        await ctx.send(embed=embed)

    @commands.command(name="ping", help="Pings the bot.")
    async def ping(self, ctx):
        await ctx.send(Config().lang(self, 'ping_out'))
        
    @commands.command(name="mud", brief="Pings the bot.")
    async def mud(self, ctx):
        await ctx.send(Config().lang(self, 'mud_out'))
        
    @commands.command(name="mudkip", brief="MUDKIP!")
    async def mudkip(self, ctx):
        await ctx.send(Config().lang(self, 'mudkip_out'))

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
        file = discord.File(f"{Config().storage_dir(self)}/treecko.jpg")
        await ctx.send(Config().lang(self, 'geck_out'), file=file)

    @commands.command(name="liebe", help="Provides love to the channel")
    async def liebe(self, ctx):
        await ctx.send(Config().lang(self, 'liebe_out'))

    @commands.command(name="danny", help="Makes an attempt to replace the user Danny by giving one of his catchphrases")
    async def danny(self, ctx):
        dannyliste = [

            'danny_out1',
            'danny_out2',
            'danny_out3',
            'danny_out4',
            'danny_out5',
            'danny_out6',
        ]
        await ctx.send(Config().lang(self, random.choice(dannyliste)))

    @commands.command(name="tippspiel", help="Gives the link to the Tippspiel-Sheet")
    async def tippspiel(self, ctx):
        await ctx.send(Config().lang(self, 'tippspiel_output'))
