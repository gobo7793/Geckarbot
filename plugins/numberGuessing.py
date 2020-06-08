import random
import logging
import discord
from discord.ext import commands

return_code = {
    "error": 0,
    "game stopped": 1,
    "game continuing": 2
}

single_game  = 0
channel_game = 1


class Plugin(commands.Cog, name="A simple number guessing game"):

    def __init__(self, bot):
        self.bot              = bot
        self.player           = None
        self.isPlaying        = False
        self.number:      int = 0
        self.guess_count: int = 0
        self.games_user       = {}
        self.games_channel    = {}

        super(commands.Cog).__init__()
        bot.register(self)

    @commands.group(name="guess", help="Guess a number",
                    description="Start a game via '!guess start'")
    async def guess(self, msg, guess=None, arg1=None, arg2=None, arg3=None):
        await msg.trigger_typing()

        # TODO ermöglichen des startens und spielens von einzel- und kanalspielen parallel

        user_id     = msg.author.id
        channel_id  = msg.channel.id
        game        = None
        list_open   = False
        list_single = False
        list_all    = False

        if guess == "status":
            # await msg.send("status")
            games = []

            if arg1 == "all" or arg1 is None:
                # await msg.send("all")
                list_open   = True
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
                test = [message]
                test.append("blubb")
                print(test)
                await msg.send(message)

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
                        if isinstance(msg.channel, discord.TextChannel):
                            game = self.start_channel(channel_id)

                        # no text channel, start single game instead
                        else:
                            await msg.send("No channel game possible. Continuing with single game.")
                            game = self.start_single(user_id)
                            arg1 = arg2
                            arg2 = arg3

                    # no channel game start wanted, start single game
                    else:
                        game = self.start_single(user_id)

            if game is not None:
                ret = await game.guess(msg, guess, arg1, arg2)
            else:
                await msg.send("Something went wrong. No actions performed.")
                ret = return_code["error"]

            # await msg.send("Return is: {}".format(ret))

            if ret == return_code["game stopped"]:
                if user_id in self.games_user:
                    del self.games_user[user_id]
                elif channel_id in self.games_channel:
                    del self.games_channel[channel_id]



    def start_single(self, user_id):
        game = NumberGuessing(single_game)
        self.games_user[user_id] = game
        return game



    def start_channel(self, channel_id):
        # logging.info("Starting Channelgame: {}".format(channel_game))
        game = NumberGuessing(channel_game)
        self.games_channel[channel_id] = game
        return game



    def append_channel_games(self, channel_id = None):
        ind = int(1)
        text = []
        text.append("**Channel games**")

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
                ind +=1
        if ind == 1:
            text.append("currently no active games")

        return text



    def append_user_games(self, user_id = None):
        ind = int(1)
        text = []
        text.append("**Single games**")

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
            text.append("currently no active games")

        return text



    def format_line(self, name, game, ind = int(0)):
        tries   = game.get_tries()
        minimum = game.get_min()
        maximum = game.get_max()
        amount = maximum - minimum + 1
        line = ""
        if ind > 0:
            line = line + "{}: ".format(ind)
        line = line + "{} (Tries: **{}**, Minimum: **{}**, Maximum: **{}**, Range: **{}** possibilities)".format(name, tries, minimum, maximum, amount)
        return line




class NumberGuessing:

    def __init__(self, gamemode):
        self.player           = None
        self.isPlaying        = False
        self.number:      int = 0
        self.guess_count: int = 0
        self.gamemode         = gamemode
        self.msg              = None
        self.min              = 0
        self.max              = 0

    async def guess(self, msg, guess=None, arg1=None, arg2=None):
        self.msg = msg
        ret = return_code["error"]
        # logging.info("Gamemode: {}".format(self.gamemode))
        # logging.info("guess: {}, arg1: {}, arg2: {}".format(guess, arg1, arg2))
        if guess == "start":
            if arg1 is not None or arg2 is not None:
                try:
                    arg1 = int(arg1)
                    arg2 = int(arg2)
                except (TypeError, ValueError):
                    await self.start()
                    ret = return_code["game continuing"]
                    return ret
                await self.start(arg1, arg2)
                ret = return_code["game continuing"]
            else:
                await self.start()
                ret = return_code["game continuing"]
        elif guess == "stop":
            await self.stop()
            ret = return_code["game stopped"]
        else:
            try:
                if guess is None:
                    guess = 0
                guess = int(guess)
            except (TypeError, ValueError):
                return
            if isinstance(guess, int) or guess is None:
                if self.isPlaying is False:
                    await self.start()
                    ret = return_code["game continuing"]
                if guess < 1:
                    guess = 0
                if guess == 0:
                    await self.send_message("Please enter a number starting from 1!")
                else:
                    self.guess_count += 1
                    if guess == self.number:
                        await self.send_message(
                            "Great job! You guessed the number **{}** in only **{}** tries!".format(self.number,
                                                                                                    self.guess_count))
                        self.reset()  # sets the variables back to start a new game
                        ret = return_code["game stopped"]
                    else:
                        if guess < self.number:
                            await self.send_message("**{}** is too low".format(guess))
                        else:
                            await self.send_message("**{}** is too high".format(guess))
                        ret = return_code["game continuing"]
        return ret

    # @guess.command(name="start", help="Starts a game if not already running")
    async def start(self, range_from: int = 1, range_to: int = 100):
        if self.isPlaying is False:
            if range_from <= 1:
                range_from = 1
            if range_to < range_from:
                range_to = range_from
            self.number = random.choice(range(range_from, range_to+1))
            self.isPlaying = True
            self.min = range_from
            self.max = range_to
            await self.send_message("You can now start guessing between **{}** and **{}**".format(range_from, range_to))
            logging.info("Identifier: {} Number: {}".format(self.msg.author.name, self.number))
        else:
            await self.send_message("Game is already started!")

    # @guess.command(name="stop", help="Stops a game and shows the number that should have been guessed")
    async def stop(self):
        if self.isPlaying is True:
            await self.send_message("Stopped the game. The number was: **{}**. Your tries so far: **{}**".format(self.number, self.guess_count))
            self.reset()  # sets the variables back to start a new game
        else:
            await self.send_message("Cannot stop game. Start game first!")

    def reset(self):
        self.number = 0
        self.guess_count = 0
        self.isPlaying = False

    async def send_message(self, content: str):
        if self.gamemode == single_game:
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