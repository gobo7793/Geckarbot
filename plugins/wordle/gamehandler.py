from asyncio import Lock
from typing import Union, List, Optional, Type
import re

from nextcord import User, Member, TextChannel, Thread, DMChannel, Message

from base.data import Config, Lang
from botutils.converters import get_best_username as gbu

from plugins.wordle.game import Game, Correctness, HelpingSolver, WORDLENGTH, Guess
from plugins.wordle.utils import format_guess, ICONS, OutOfOptions, format_game_result
from plugins.wordle.wordlist import WordList


class AlreadyRunning(Exception):
    """
    Raised by Mothership.spawn() if the player, channel combination already exists.
    """
    pass


class BaseGameInstance:
    """
    base class for game instances; keeps bookkeeping data such as channel, player
    """
    def __init__(
            self,
            plugin,
            player: Union[User, Member],
            channel: Union[TextChannel, DMChannel, Thread],
            game: Game
    ):
        self.plugin = plugin
        self.player = player
        self.channel = channel
        self.game = game

    async def on_message(self, msg: Message):
        """
        Called by mothership whenever player sends a message with length WORDLENGTH to channel.

        :param msg: Message that was sent
        """
        raise NotImplementedError

    async def respawn(self):
        """
        Called when a spawn was attempted by this instance's player, channel combination.
        """
        raise NotImplementedError

    async def play(self):
        """
        Called to start the game.
        """
        raise NotImplementedError

    async def suggest(self):
        """
        Called when the sugges command is invoked on this instance.
        """
        raise NotImplementedError


class GameInstance(BaseGameInstance):
    """
    UI for a discord wordle game.
    """
    def __init__(
            self,
            plugin,
            wordlist: WordList,
            player: Union[User, Member],
            channel: Union[TextChannel, DMChannel, Thread],
            solver_class: Type[HelpingSolver],
            solution: Optional[str] = None
    ):
        super().__init__(plugin, player, channel, Game(wordlist, word=solution))
        if solution is None:
            self.game.set_random_solution()

        self.respawned = False  # set to True if spawn is called again on this instance
        self.guess_lock = Lock()
        self.has_been_helped = False

        self.solver = solver_class(self.game)

    async def play(self):
        await self.channel.send(Lang.lang(self.plugin, "play_intro"))

    def format_result(self) -> str:
        """
        Formats the result of the game.
        """
        d = self.game.done
        if d == Correctness.CORRECT:
            return "{}/{}".format(len(self.game.guesses), self.game.max_tries)
        if d == Correctness.INCORRECT:
            whb = Lang.lang(self.plugin, "play_wouldhavebeen", self.game.solution)
            return "X/{}\n{}".format(self.game.max_tries, whb)
        return "This should not happen, pls report."

    async def suggest(self):
        suggestion = self.solver.get_guess()
        await self.channel.send(Lang.lang(self.plugin, "play_suggestion", suggestion))
        self.has_been_helped = True

    async def respawn(self):
        """
        Re-sends the last guess response.
        """
        # Send generic message when no guesses have been sent so far
        if len(self.game.guesses) == 0:
            if isinstance(self.channel, DMChannel):
                chan = Lang.lang(self.plugin, "dmchannel")
            else:
                chan = self.channel.mention
            await self.channel.send(Lang.lang(self.plugin, "play_error_game_exists", gbu(self.player), chan))
            return

        self.respawned = True
        pname = gbu(self.player) if self.plugin.mothership.game_count(self.channel) > 1 else None
        await self.channel.send(format_guess(self.plugin, self.game, self.game.guesses[0],
                                             player_name=pname, history=True))

    async def on_message(self, msg: Message):
        """
        Handles a guess.

        :param msg: Message that contains the guessed word
        """
        history = self.plugin.get_config("format_guess_history")
        word = re.sub(r"\s*", "", msg.content).lower()
        assert len(word) == WORDLENGTH

        async with self.guess_lock:
            if self.game.done != Correctness.PARTIALLY:
                # already done
                return

            try:
                guess = self.game.guess(word)
            except ValueError:
                await self.channel.send(Lang.lang(self.plugin, "not_in_wordlist"))
                return
            self.solver.digest_guess(guess)

            pname = gbu(self.player) if self.plugin.mothership.game_count(self.channel) > 1 else None
            if self.game.done == Correctness.PARTIALLY:
                # mid-game
                await self.channel.send(format_guess(self.plugin, self.game, guess, player_name=pname, history=history))
            else:
                # done
                kb = self.game.done == Correctness.CORRECT
                await self.channel.send(format_guess(self.plugin, self.game, guess,
                                                     player_name=pname, done=kb, history=history))
                await self.channel.send(self.format_result())
                self.plugin.mothership.deregister(self)


class ReverseGameInstance(BaseGameInstance):
    """
    UI for a reverse wordle game where the player answers the bot's guesses.
    """
    def __init__(
            self,
            plugin,
            wordlist: WordList,
            player: Union[User, Member],
            channel: Union[TextChannel, DMChannel, Thread],
            solver_class: Type[HelpingSolver]
    ):
        super().__init__(plugin, player, channel, Game(wordlist))
        self.ui = {
            Correctness.INCORRECT: "x" + ICONS[Correctness.INCORRECT],
            Correctness.PARTIALLY: "p" + ICONS[Correctness.PARTIALLY],
            Correctness.CORRECT: "r" + ICONS[Correctness.CORRECT]
        }
        self.solver = solver_class(self.game)
        self.last_guess: Optional[str] = None

    async def suggest(self):
        """
        Calculates the next guess and sends it.
        """
        if not self.last_guess:
            try:
                self.last_guess = self.solver.get_guess()
            except OutOfOptions:
                await self.channel.send(Lang.lang(self.plugin, "reverse_concede"))
                self.plugin.mothership.deregister(self)
                return

        prefix = ""
        if self.plugin.mothership.game_count(self.channel) > 1:
            prefix = Lang.lang(self.plugin, "reverse_username_prefix", gbu(self.player))

        await self.channel.send(Lang.lang(self.plugin, "reverse_guess", prefix, self.last_guess))

    async def on_message(self, msg: Message):
        # parse response
        response = list(re.sub(r"\s*", "", msg.content))
        assert len(response) == WORDLENGTH
        for i in range(len(response)):
            found = False
            for correctness, icon in self.ui.items():
                if response[i] in icon:
                    found = True
                    response[i] = correctness
                    break
            if not found:
                await self.channel.send(Lang.lang(self.plugin, "reverse_parse_error"))
                return

        # build guess
        assert self.last_guess is not None
        g = Guess(self.last_guess, response)
        self.last_guess = None
        self.game.guesses.append(g)
        self.solver.digest_guess(g)

        done = False
        if g.is_correct:
            done = True
            await self.channel.send(Lang.lang(self.plugin, "reverse_success"))
            self.plugin.mothership.deregister(self)
        elif self.game.done == Correctness.INCORRECT:
            done = True
            await self.channel.send(Lang.lang(self.plugin, "reverse_failure"))
            self.plugin.mothership.deregister(self)

        if done:
            f = format_guess(self.plugin, self.game, self.game.guesses[-1], done=True, history=True)
            await self.channel.send("{}\n{}".format(format_game_result(self.plugin, self.game), f))
            return

        await self.suggest()

    async def respawn(self):
        await self.suggest()

    async def play(self):
        await self.suggest()


class Mothership:
    """
    Handles running wordle games.
    """
    def __init__(self, plugin):
        self.bot = Config().bot
        self.plugin = plugin
        self.instances: List[BaseGameInstance] = []

    async def on_message(self, message):
        msg = re.sub(r"\s*", "", message.content)
        if len(msg) != WORDLENGTH:
            return

        # find instance
        instance = self.get_instance(message.channel, message.author)
        if instance is not None:
            await instance.on_message(message)

    def game_count(self, channel) -> int:
        """
        :param channel: Channel
        :return: Amount of games in `channel`
        """
        r = 0
        for el in self.instances:
            if el.channel == channel:
                r += 1
        return r

    def get_instance(self, channel, player) -> Optional[BaseGameInstance]:
        """
        :param channel: channel
        :param player: player
        :return: GameInstance for this channel, player pair. Returns None if there is none.
        """
        for el in self.instances:
            if channel == el.channel and player == el.player:
                return el
        return None

    async def catch_respawn(self, player, channel) -> Optional[BaseGameInstance]:
        """
        Checks if there is a game in the channel and if so, executes its respawn() method.

        :param player: Player
        :param channel: Channel
        :return: instance that was found
        """
        for el in self.instances:
            if el.player == player and el.channel == channel:
                await el.respawn()
                return el
        return None

    async def spawn(self, plugin, wordlist: WordList, player, channel, solver_class: Type[HelpingSolver],
                    solution: Optional[str] = None) -> GameInstance:
        """
        Starts a new game instance for a player, channel combination.

        :param plugin: Plugin ref
        :param wordlist: Wordlist that this instance is to be run on
        :param player: player
        :param channel: channel the wordle is played in
        :param solution: spawn a game with this solution
        :param solver_class: solver to accompany this game instance
        :return: spawned GameInstance
        """
        instance = GameInstance(plugin, wordlist, player, channel, solver_class, solution=solution)
        self.instances.append(instance)
        await instance.play()
        return instance

    async def spawn_reverse(self, plugin, wordlist: WordList, player, channel,
                            solver_class: Type[HelpingSolver]) -> ReverseGameInstance:
        """
        Spawns a reverse game instance.

        :param plugin: Plugin ref
        :param wordlist: Wordlist that this instance is to be run on
        :param player: Player
        :param channel: Channel the reverse wordle is played in
        :param solver_class: solver that is used by the bot
        :return: spawned ReverseGameInstance
        """
        instance = ReverseGameInstance(plugin, wordlist, player, channel, solver_class)
        self.instances.append(instance)
        await instance.play()
        return instance

    def deregister(self, instance: BaseGameInstance):
        """
        :param instance: Instance to deregister
        """
        self.instances.remove(instance)
