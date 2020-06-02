import discord
import random
import logging
from discord.ext import commands


class numberGuessing(commands.Cog, name="A simple number guessing game"):

    def __init__(self, bot):
        self.bot = bot
        self.player = None
        self.isPlaying = False
        self.number: int = 0
        self.guess_count: int = 0

    @commands.group(name="guess", help="Guess a number",
                    description="Start a game via '!guess start'")
    async def guess(self, ctx, guess = None):
        await ctx.send(str(ctx.invoked_subcommand))
        if ctx.invoked_subcommand is None:
            guess_int = int(guess)
            del guess
            guess = guess_int
            if isinstance(guess, int):
                await ctx.send("Guessing!")
                if self.isPlaying == False:
                    await self.start(ctx)
                if guess < 1:
                    guess = 0
                if guess == 0:
                    await ctx.send("Please enter a number starting from 1!")
                else:
                    self.guess_count += 1
                    if guess == self.number:
                        await ctx.send(
                            "Great job! You guessed the number **{}** in only **{}** tries!".format(self.number,
                                                                                                    self.guess_count))
                        self.number = 0
                        self.guess_count = False
                        self.isPlaying = False
                    else:
                        if guess < self.number:
                            await ctx.send("**{}** is too low".format(guess))
                        else:
                            await ctx.send("**{}** is too high".format(guess))

    @guess.command(name="start", help="Starts a game if not already running")
    async def start(self, ctx, range_from: int = 1, range_to: int = 100):
        if self.isPlaying == False:
            if range_from <= 1:
                range_from = 1
            if range_to < range_from:
                range_to = range_from
            self.number = random.choice(range(range_from, range_to))
            self.isPlaying = True
            await ctx.send("You can now start guessing between **{}** and **{}**".format(range_from, range_to))
            logging.info("Number: {}".format(self.number))
        else:
            await ctx.send("Game is already started!")

    @guess.command(name="stop", help="Stops a game and shows the number that should have been guessed")
    async def stop(self, ctx):
        await ctx.send("Testttttt")
        """
        await ctx.send("Stopped the game. The number was: **{}**".format(self.number))
        if self.isPlaying == True:
            self.isPlaying = False
            await ctx.send("Stopped the game. The number was: **{}**".format(self.number))
        else:
            await ctx.send("Cannot stop game. Start game first!")
        """


def register(bot):
    bot.add_cog(numberGuessing(bot))
