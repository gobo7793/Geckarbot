import random
import logging
from discord.ext import commands


class Plugin(commands.Cog, name="A simple number guessing game"):

    def __init__(self, bot):
        self.bot = bot
        self.player = None
        self.isPlaying = False
        self.number: int = 0
        self.guess_count: int = 0

        super(commands.Cog).__init__()
        bot.register(self)

    def default_config(self):
        return {}

    @commands.group(name="guess", help="Guess a number",
                    description="Start a game via '!guess start'")
    async def guess(self, ctx, guess=None, arg1=None, arg2=None):
        if guess == "start":
            if arg1 is not None or arg2 is not None:
                try:
                    arg1 = int(arg1)
                    arg2 = int(arg2)
                except (TypeError, ValueError):
                    await self.start(ctx)
                    return
                await self.start(ctx, arg1, arg2)
            else:
                await self.start(ctx)
        elif guess == "stop":
            await self.stop(ctx)
        else:
            try:
                if guess is None:
                    guess = 0
                guess = int(guess)
            except (TypeError, ValueError):
                return
            if isinstance(guess, int) or guess is None:
                if self.isPlaying is False:
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
                        self.reset()  # sets the variables back to start a new game
                    else:
                        if guess < self.number:
                            await ctx.send("**{}** is too low".format(guess))
                        else:
                            await ctx.send("**{}** is too high".format(guess))

    @guess.command(name="start", help="Starts a game if not already running")
    async def start(self, ctx, range_from: int = 1, range_to: int = 100):
        if self.isPlaying is False:
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
        if self.isPlaying is True:
            await ctx.send("Stopped the game. The number was: **{}**".format(self.number))
            self.reset()  # sets the variables back to start a new game
        else:
            await ctx.send("Cannot stop game. Start game first!")

    def reset(self):
        self.number = 0
        self.guess_count = 0
        self.isPlaying = False
