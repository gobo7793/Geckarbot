from asyncio import Lock
from typing import Union, List, Optional, Type

from nextcord import User, Member, TextChannel, Thread, DMChannel, Message

from base.data import Config, Lang
from botutils.converters import get_best_username as gbu

from plugins.wordle.game import Game, Correctness, HelpingSolver
from plugins.wordle.utils import format_guess
from plugins.wordle.wordlist import WordList


class AlreadyRunning(Exception):
    """
    Raised by Mothership.spawn() if the player, channel combination already exists.
    """
    pass


class GameInstance:
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
        self.plugin = plugin
        self.game = Game(wordlist, word=solution)
        self.player = player
        self.channel = channel
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

    async def guess(self, msg: Message):
        """
        Handles a guess.

        :param msg: Message that contains the guessed word
        """
        history = self.plugin.get_config("format_guess_history")
        word = msg.content.strip().lower()
        assert len(word) == 5

        async with self.guess_lock:
            if self.game.done != Correctness.PARTIALLY:
                # already done
                return

            try:
                guess = self.solver.guess(word)
            except ValueError:
                await self.channel.send(Lang.lang(self.plugin, "not_in_wordlist"))
                return

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


class Mothership:
    """
    Handles running wordle games.
    """
    def __init__(self, plugin):
        self.bot = Config().bot
        self.plugin = plugin
        self.instances: List[GameInstance] = []

    async def on_message(self, message):
        if len(message.content.strip()) != 5:
            return

        # find instance
        instance = self.get_instance(message.channel, message.author)
        if instance is not None:
            await instance.guess(message)

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

    def get_instance(self, channel, player) -> Optional[GameInstance]:
        """
        :param channel: channel
        :param player: player
        :return: GameInstance for this channel, player pair. Returns None if there is none.
        """
        for el in self.instances:
            if channel == el.channel and player == el.player:
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
        :raises AlreadyRunning: If there is an instance for this player, channel combination without guesses.
        """
        for el in self.instances:
            if el.player == player and el.channel == channel:
                if len(el.game.guesses) == 0:
                    raise AlreadyRunning
                el.respawned = True
                pname = gbu(player) if self.game_count(channel) > 1 else None
                await el.channel.send(format_guess(plugin, el.game, el.game.guesses[0],
                                                   player_name=pname, history=True))
                return el

        instance = GameInstance(plugin, wordlist, player, channel, solver_class, solution=solution)
        self.instances.append(instance)
        await instance.play()
        return instance

    def deregister(self, instance: GameInstance):
        self.instances.remove(instance)
