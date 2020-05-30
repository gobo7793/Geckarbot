import random

import discord
from discord.ext import commands

class funCommands(commands.Cog, name="Funny/Misc Commands"):
    """Funny and miscellaneous commands without other category"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="roll_dice", brief="Simulates rolling dice.",
                     usage="[NumberOfSides] [NumberOfDices]")
    async def roll(self, ctx, number_of_sides:int=6, number_of_dice:int=1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        await ctx.send(', '.join(dice))
