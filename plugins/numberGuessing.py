import random
import logging
from enum import Enum

import discord
from discord.ext import commands

from base import BasePlugin
from conf import Lang
from subsystems import help


class ReturnCode(Enum):
    ERROR = 0
    STOPPED = 1
    CONTINUING = 2


class Gamemode(Enum):
    SINGLE = 0
    CHANNEL = 1


class Plugin(BasePlugin, name="A simple number guessing game"):

    def __init__(self, bot):
        self.bot = bot
        self.player = None
        self.isPlaying = False
        self.number: int = 0
        self.guess_count: int = 0
        self.games_user = {}
        self.games_channel = {}

        super().__init__(bot)
        bot.register(self, help.DefaultCategories.GAMES)

    def default_storage(self):
        return {}

    @commands.group(name="guess", help="Guess a number",
                    description="Start a game via '!guess start'")
    async def guess(self, ctx, guess=None, arg1=None, arg2=None, arg3=None):
        await ctx.trigger_typing()

        # TODO ermöglichen des startens und spielens von einzel- und kanalspielen parallel

        user_id = ctx.author.id
        channel_id = ctx.channel.id
        list_open = False
        list_single = False
        list_all = False

        if guess == "status":
            # await msg.send("status")
            games = []

            if arg1 == "all" or arg1 is None:
                # await msg.send("all")
                list_open = True
                list_single = True
                if arg1 == "all":
                    list_all = True
            if arg1 == "channel" or list_open is True:
                # await msg.send("open")
                if arg2 == "all" or list_all is True:
                    channel_games = self.append_channel_games()
                else:
                    channel_games = self.append_channel_games(channel_id)
                games.append("")
                games = games + channel_games
                print(games)
            if arg1 == "single" or list_single is True:
                # await msg.send("single")
                if arg2 == "all" or list_all is True:
                    single_games = self.append_user_games()
                else:
                    single_games = self.append_user_games(user_id)
                games.append("")
                games = games + single_games
                print(games)
            message = str()
            first_line = True
            for line in games:
                if first_line is False:
                    message = message + "\n"
                else:
                    first_line = False
                message = message + line
            if len(message) > 0:
                await ctx.send(message)

        else:
            # search existing single game
            if user_id in self.games_user:
                game = self.games_user[user_id]

            # if single game start wanted
            elif guess == "start" and arg1 == "single":
                game = self.start_single(user_id)
                arg1 = arg2
                arg2 = arg3

            # no single game active or wanted
            else:
                # search existing channel game
                if channel_id in self.games_channel:
                    game = self.games_channel[channel_id]

                # no channel game active
                else:
                    # if channel game start wanted
                    if guess == "start" and arg1 == "channel":
                        arg1 = arg2
                        arg2 = arg3

                        # if text channel (otherwise not possible)
                        if isinstance(ctx.channel, discord.TextChannel):
                            game = self.start_channel(channel_id)

                        # no text channel, start single game instead
                        else:
                            await ctx.send(Lang.lang(self, 'channelgame_not_possible'))
                            game = self.start_single(user_id)
                            arg1 = arg2
                            arg2 = arg3

                    # no channel game start wanted, start single game
                    else:
                        game = self.start_single(user_id)

            if game is not None:
                ret = await game.guess(ctx, guess, arg1, arg2)
            else:
                await ctx.send(Lang.lang(self, 'error_msg'))
                ret = ReturnCode.ERROR

            # await msg.send("Return is: {}".format(ret))

            if ret == ReturnCode.STOPPED:
                if user_id in self.games_user:
                    del self.games_user[user_id]
                elif channel_id in self.games_channel:
                    del self.games_channel[channel_id]

    def start_single(self, user_id):
        game = NumberGuessing(self, Gamemode.SINGLE)
        self.games_user[user_id] = game
        return game

    def start_channel(self, channel_id):
        # logging.info("Starting Channelgame: {}".format(channel_game))
        game = NumberGuessing(self, Gamemode.CHANNEL)
        self.games_channel[channel_id] = game
        return game

    def append_channel_games(self, channel_id=None):
        ind = int(1)
        text = ["**Channel games**"]

        if channel_id is None:
            for channel_id in self.games_channel.keys():
                name = str(self.bot.get_channel(channel_id))
                game = self.games_channel[channel_id]
                text.append(self.format_line(name, game, ind))
                ind += 1
        else:
            if channel_id in self.games_channel:
                name = str(self.bot.get_channel(channel_id))
                game = self.games_channel[channel_id]
                text.append(self.format_line(name, game))
                ind += 1
        if ind == 1:
            text.append(Lang.lang(self, 'no_active_games'))

        return text

    def append_user_games(self, user_id=None):
        ind = int(1)
        text = ["**Single games**"]

        if user_id is None:
            for user_id in self.games_user.keys():
                name = str(self.bot.get_user(user_id))
                game = self.games_user[user_id]
                text.append(self.format_line(name, game, ind))
                ind += 1
        else:
            if user_id in self.games_user:
                name = str(self.bot.get_user(user_id))
                game = self.games_user[user_id]
                text.append(self.format_line(name, game))
                ind += 1
        if ind == 1:
            text.append(Lang.lang(self, 'no_active_games'))

        return text

    def format_line(self, name, game, ind=int(0)):
        tries = game.get_tries()
        minimum = game.get_min()
        maximum = game.get_max()
        amount = maximum - minimum + 1
        line = ""
        if ind > 0:
            line += "{}: ".format(ind)
        line += Lang.lang(self, 'game_statistics', name, tries, minimum, maximum, amount)
        return line


class NumberGuessing:

    def __init__(self, plugin, gamemode):
        self.plugin = plugin
        self.player = None
        self.isPlaying = False
        self.number: int = 0
        self.guess_count: int = 0
        self.gamemode = gamemode
        self.msg = None
        self.min = 0
        self.max = 0

    async def guess(self, msg, guess=None, arg1=None, arg2=None):
        self.msg = msg
        # logging.info("Gamemode: {}".format(self.gamemode))
        # logging.info("guess: {}, arg1: {}, arg2: {}".format(guess, arg1, arg2))
        if guess is None:
            await self.start()
            return ReturnCode.CONTINUING
        elif guess == "start":
            try:
                if arg1 and arg2:
                    await self.start(int(arg1), int(arg2))
                else:
                    await self.start(range_to=int(arg1))
            except (TypeError, ValueError):
                await self.start()
            return ReturnCode.CONTINUING
        elif guess == "stop":
            await self.stop()
            return ReturnCode.STOPPED
        else:
            try:
                guess = int(guess)
            except (TypeError, ValueError):
                await self.send_message(Lang.lang(self.plugin, 'invalid_number'))
                return

            if self.isPlaying is False:
                await self.start()

            if guess < 1:
                await self.send_message(Lang.lang(self.plugin, 'invalid_number'))
            else:
                self.guess_count += 1
                if guess == self.number:
                    await self.send_message(
                        Lang.lang(self.plugin, 'guess_won', self.number, self.guess_count))
                    self.reset()  # sets the variables back to start a new game
                    return ReturnCode.STOPPED
                else:
                    if guess < self.number:
                        await self.send_message(Lang.lang(self.plugin, 'guess_too_low', guess))
                    else:
                        await self.send_message(Lang.lang(self.plugin, 'guess_too_big', guess))
                return ReturnCode.CONTINUING
            return ReturnCode.ERROR

    # @guess.command(name="start", help="Starts a game if not already running")
    async def start(self, range_from: int = 1, range_to: int = 100):
        if self.isPlaying is False:
            if range_from <= 1:
                range_from = 1
            if range_to < range_from:
                range_to = range_from
            self.number = random.choice(range(range_from, range_to + 1))
            self.isPlaying = True
            self.min = range_from
            self.max = range_to
            await self.send_message(Lang.lang(self.plugin, 'guess_started', range_from, range_to))
            logging.info("Identifier: {} Number: {}".format(self.msg.author.name, self.number))
        else:
            await self.send_message(Lang.lang(self.plugin, 'guess_already_started'))

    # @guess.command(name="stop", help="Stops a game and shows the number that should have been guessed")
    async def stop(self):
        if self.isPlaying is True:
            await self.send_message(
                Lang.lang(self.plugin, 'guess_stopped', self.number, self.guess_count))
            self.reset()  # sets the variables back to start a new game
        else:
            await self.send_message(Lang.lang(self.plugin, 'guess_cannot_stop'))

    def reset(self):
        self.number = 0
        self.guess_count = 0
        self.isPlaying = False

    async def send_message(self, content: str):
        if self.gamemode == Gamemode.SINGLE:
            message = "[{}] ".format(self.msg.author.name) + content
        else:
            message = "[channel] " + content
        await self.msg.send(message)

    def get_tries(self):
        return self.guess_count

    def get_min(self):
        return self.min

    def get_max(self):
        return self.max
