import random

import discord
from discord.ext import commands

class funCommands(commands.Cog):
    """Funny commands without other category"""

    @commands.command(name="roll_dice", brief="Simulates rolling dice.",
                     usage="<NumberOfDices> <NumberOfSides>")
    async def roll(self, ctx, number_of_dice: int, number_of_sides: int):
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        await ctx.send(', '.join(dice))
