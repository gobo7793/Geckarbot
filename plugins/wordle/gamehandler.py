from asyncio import Lock
from typing import Union, List

from nextcord import User, Member, TextChannel, Thread, DMChannel, Message

from base.data import Config, Lang
from plugins.wordle.game import Game, Correctness, Guess, WORDLENGTH
from plugins.wordle.wordlist import WordList


ICONS = {
    Correctness.CORRECT: "🟩",
    Correctness.PARTIALLY: "🟨",
    Correctness.INCORRECT: "⬛",
}


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
            channel: Union[TextChannel, DMChannel, Thread]
    ):
        self.plugin = plugin
        self.game = Game(wordlist)
        self.player = player
        self.channel = channel
        self.respawned = False  # set to True if spawn is called again on this instance
        self.guess_lock = Lock()

    async def play(self):
        await self.channel.send(Lang.lang(self.plugin, "play_intro"))

    def format_guess(self, guess: Guess, done: bool = False, history: bool = False) -> str:
        """
        Formats the output string for a guess.

        :param guess: Guess instance that is to be formatted
        :param done: if set to True, keyboard is strictly omitted
        :param history: if set to True, shows all the guesses so far
        :return: formatted string
        """
        mono = self.plugin.get_config("format_guess_monospace")
        uppercase = self.plugin.get_config("format_guess_uppercase")
        show_word = self.plugin.get_config("format_guess_include_word")

        # format correctness
        guesses = self.game.guesses if history else [guess]
        r = []

        # vertical
        if self.plugin.get_config("format_guess_vertical"):
            for i in range(WORDLENGTH):
                line = []
                for el in guesses:
                    word = el.word.upper() if uppercase else el.word
                    if show_word:
                        line.append("{} {}".format(ICONS[el.correctness[i]], word[i]))
                    else:
                        line.append(ICONS[el.correctness[i]])
                r.append("  ".join(line))
            r = "\n".join(r)

        # horizontal
        else:
            r = []
            for el in guesses:
                word = el.word.upper() if uppercase else el.word
                correctness = []
                for i in range(WORDLENGTH):
                    correctness.append(ICONS[el.correctness[i]])
                correctness = "".join(correctness)
                if show_word:
                    r.append("{}\n{}".format(word, correctness))
                else:
                    r.append(correctness)
            r = "\n\n".join(r)
        if not mono:
            r = "_ _\n" + r

        # format keyboard
        if not done and self.plugin.get_config("format_guess_keyboard"):
            kb_mono = self.plugin.get_config("format_guess_keyboard_monospace")
            found_l, out_l, unused_l = self.game.alphabet(uppercase=uppercase)
            delimiter = self.plugin.get_config("format_guess_keyboard_gap")

            found_s = None
            if found_l:
                found_s = delimiter.join(found_l)
                found_s = "{} {}".format(found_s, Lang.lang(self.plugin, "play_keyboard_found"))

            unused_s = None
            if unused_l:
                unused_s = delimiter.join(unused_l)
                unused_s = "{} {}".format(unused_s, Lang.lang(self.plugin, "play_keyboard_unused"))

            out_s = None
            if out_l:
                out_s = delimiter.join(out_l)
                if not kb_mono and self.plugin.get_config("format_guess_keyboard_strike"):
                    out_s = "~~{}~~".format(out_s)
                out_s = "{} {}".format(out_s, Lang.lang(self.plugin, "play_keyboard_out"))

            keyboard = []
            for el in found_s, out_s, unused_s:
                if el:
                    keyboard.append(el)
            keyboard = "\n".join(keyboard)

            # put things in monospace
            if mono:
                if kb_mono:
                    r = "```\n{}\n\n{}\n```".format(r, keyboard)
                else:
                    r = "```\n{}\n```\n\n{}\n".format(r, keyboard)
            else:
                if kb_mono:
                    r = "{}\n\n```\n{}\n```".format(r, keyboard)
                else:
                    r = "{}\n\n{}".format(r, keyboard)

        elif mono:
            r = "```\n{}\n```".format(r)

        return r

    def format_result(self):
        """
        Formats the result of the game.
        """
        d = self.game.done
        if d == Correctness.CORRECT:
            return "{}/{}".format(len(self.game.guesses), self.game.MAXTRIES)
        if d == Correctness.INCORRECT:
            whb = Lang.lang(self.plugin, "play_wouldhavebeen", self.game.solution)
            return "X/{}\n{}".format(self.game.MAXTRIES, whb)
        if d == Correctness.PARTIALLY:
            return "Game not done yet; this message should not be shown (pls report)"

    async def guess(self, msg: Message):
        """
        Handles a guess.

        :param msg: Message that contains the guessed word
        """
        history = self.plugin.get_config("format_guess_history")
        word = msg.content.strip()
        assert len(word) == 5

        async with self.guess_lock:
            if self.game.done != Correctness.PARTIALLY:
                # already done
                return

            try:
                guess = self.game.guess(word)
            except ValueError:
                await self.channel.send(Lang.lang(self.plugin, "play_not_in_list"))
                return

            if self.game.done == Correctness.PARTIALLY:
                # mid-game
                await self.channel.send(self.format_guess(guess, history=history))
            else:
                # done
                kb = False if Correctness.INCORRECT else True
                await self.channel.send(self.format_guess(guess, done=kb, history=history))
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
        for el in self.instances:
            if message.channel == el.channel and message.author == el.player:
                await el.guess(message)
                break

    async def spawn(self, plugin, wordlist, player, channel) -> GameInstance:
        """
        Starts a new game instance for a player, channel combination.

        :param plugin: Plugin ref
        :param wordlist: Wordlist that this instance is to be run on
        :param player: player
        :param channel: channel the wordle is played in
        :return: spawned GameInstance
        """
        for el in self.instances:
            if el.player == player and el.channel == channel:
                if len(el.game.guesses) == 0:
                    raise AlreadyRunning
                el.respawned = True
                await el.channel.send(el.format_guess(el.game.guesses[0], history=True))
                return el

        instance = GameInstance(plugin, wordlist, player, channel)
        self.instances.append(instance)
        await instance.play()
        return instance

    def deregister(self, instance: GameInstance):
        self.instances.remove(instance)
