from enum import Enum
from typing import Dict, Any, Optional

from base.data import Lang

from plugins.wordle.game import Game, Guess, WORDLENGTH, Correctness
from plugins.wordle.wordlist import Parsers

ICONS = {
    Correctness.CORRECT: "🟩",
    Correctness.PARTIALLY: "🟨",
    Correctness.INCORRECT: "⬛",
}


class OutOfOptions(Exception):
    """
    Raised by solvers to indicate that they ran out of possible guesses
    """
    pass


class FormatOptions(Enum):
    """
    Enum for wordle guess/history format options
    """
    MONOSPACE = "format_guess_monospace"
    INCLUDE_WORD = "format_guess_include_word"
    VERTICAL = "format_guess_vertical"
    HISTORY = "format_guess_history"
    LETTER_GAP = "format_guess_letter_gap"
    GUESS_GAP = "format_guess_guess_gap"
    CORRECTNESS_GAP = "format_guess_correctness_gap"
    KEYBOARD = "format_guess_keyboard"
    KEYBOARD_GAP = "format_guess_keyboard_gap"
    KEYBOARD_STRIKE = "format_guess_keyboard_strike"
    KEYBOARD_MONOSPACE = "format_guess_keyboard_monospace"
    UPPERCASE = "format_guess_uppercase"
    LETTER_EMOJI = "format_guess_letter_emoji"


class GuessFormat:
    """
    Container for a set of format options
    """
    def __init__(self, plugin, options_dict: Optional[Dict[FormatOptions, Any]] = None):
        """

        :param plugin: Plugin ref
        :param options_dict: format options dict, can be incomplete
        """
        if not options_dict:
            options_dict = {}
        self.options = options_dict

        # fill dict
        for key in FormatOptions:
            self.options[key] = self.options.get(key, plugin.get_config(key.value))

    @property
    def monospace(self):
        return self.options[FormatOptions.MONOSPACE]

    @property
    def include_word(self):
        return self.options[FormatOptions.INCLUDE_WORD]

    @property
    def vertical(self):
        return self.options[FormatOptions.VERTICAL]

    @property
    def history(self):
        return self.options[FormatOptions.HISTORY]

    @property
    def letter_gap(self):
        return self.options[FormatOptions.LETTER_GAP]

    @property
    def guess_gap(self):
        return self.options[FormatOptions.GUESS_GAP]

    @property
    def correctness_gap(self):
        return self.options[FormatOptions.CORRECTNESS_GAP]

    @property
    def keyboard(self):
        return self.options[FormatOptions.KEYBOARD]

    @property
    def keyboard_gap(self):
        return self.options[FormatOptions.KEYBOARD_GAP]

    @property
    def keyboard_strike(self):
        return self.options[FormatOptions.KEYBOARD_STRIKE]

    @property
    def keyboard_monospace(self):
        return self.options[FormatOptions.KEYBOARD_MONOSPACE]

    @property
    def uppercase(self):
        return self.options[FormatOptions.UPPERCASE]

    @property
    def letter_emoji(self):
        return self.options[FormatOptions.LETTER_EMOJI]


def format_word(word: str, format_options: Optional[GuessFormat] = None,
                ignore_emoji: bool = False, ignore_word_gap: bool = False) -> str:
    """
    Formats a word according to format_options.

    :param word: word to format
    :param format_options: GuessFormat with format rules
    :param ignore_emoji: If set to `True`, ignores the `letter_emoji option
    :param ignore_word_gap: If set to `True`, sets the word gap to `""`
    :return:
    """
    delimiter = "" if ignore_word_gap else format_options.letter_gap
    if not ignore_emoji and format_options.letter_emoji:
        r = []
        for char in word:
            r.append(Lang.letter_emoji(char))
        return delimiter.join(r)
    if format_options.uppercase:
        return delimiter.join(word).upper()
    return delimiter.join(word).upper()


def format_game_result(plugin, game) -> str:
    """
    Formats the result of a game.

    :param plugin: plugin ref
    :param game: game
    """
    d = game.done
    if d == Correctness.CORRECT:
        return "{}/{}".format(len(game.guesses), game.max_tries)
    if d == Correctness.INCORRECT:
        whb = "\n" + Lang.lang(plugin, "play_wouldhavebeen", game.solution) if game.solution else ""
        return "X/{}{}".format(game.max_tries, whb)
    return "This should not happen, pls report."


def format_daily(plugin, parser: Parsers, game: Game, info: Any) -> str:
    """
    Formats a game to be used as a spoilerless daily output.

    :param plugin: Plugin ref
    :param parser: Parsers instance that refers to the parser that was used to retrieve the daily
    :param game: Game to format
    :param info: parser-specific info as returned by `Parser.fetch_daily()`
    :return: Formatted string
    """
    assert game.done
    options = {
        FormatOptions.MONOSPACE: False,
        FormatOptions.INCLUDE_WORD: False,
        FormatOptions.VERTICAL: False,
        FormatOptions.HISTORY: True,
        FormatOptions.LETTER_GAP: "",
        FormatOptions.CORRECTNESS_GAP: "",
        FormatOptions.GUESS_GAP: "",
        FormatOptions.KEYBOARD: False,
    }

    f = format_guess(plugin, game, game.guesses[-1], GuessFormat(plugin, options), history=True)
    return "Wordle {} {}/{}\n{}".format(info, len(game.guesses), game.max_tries, f)


def format_guess(plugin, game: Game, guess: Guess,
                 format_options: Optional[GuessFormat] = None, player_name: Optional[str] = None,
                 done: bool = False, history: bool = False) -> str:
    """
    Formats the output string for a guess.

    :param plugin: Plugin ref
    :param game: Game that is being solved
    :param guess: Guess instance that is to be formatted
    :param format_options: GuessFormat that controls what the resulting formatted guess looks like
    :param player_name: Player name that is put at the front
    :param done: if set to True, keyboard is strictly omitted
    :param history: if set to True, shows all the guesses so far
    :return: formatted string
    """
    if format_options is None:
        format_options = GuessFormat(plugin)

    # format correctness
    guesses = game.guesses if history else [guess]
    r = []

    # vertical
    if format_options.vertical:
        for i in range(WORDLENGTH):
            line = []
            for el in guesses:
                word = format_word(el.word, format_options)
                if format_options.include_word:
                    line.append("{} {}".format(word[i], ICONS[el.correctness[i]]))
                else:
                    line.append(ICONS[el.correctness[i]])
            r.append("  ".join(line))
        r = "\n".join(r)

    # horizontal
    else:
        r = []
        for el in guesses:
            word = format_word(el.word, format_options)
            correctness = []
            for i in range(WORDLENGTH):
                correctness.append(ICONS[el.correctness[i]])
            correctness = format_options.correctness_gap.join(correctness)
            if format_options.include_word:
                r.append("{}\n{}".format(word, correctness))
            else:
                r.append(correctness)
        r = "\n{}".format(format_options.guess_gap).join(r)

    # Add username if necessary
    if player_name:
        r = "{}:\n\n{}".format(player_name, r)

    if not format_options.monospace:
        r = "_ _\n" + r

    # format keyboard
    if not done and format_options.keyboard:
        found_l, out_l, unused_l = game.alphabet(uppercase=format_options.uppercase)

        found_s = None
        if found_l:
            found_s = format_options.keyboard_gap.join(found_l)
            found_s = "{} {}".format(found_s, Lang.lang(plugin, "play_keyboard_found"))

        unused_s = None
        if unused_l:
            unused_s = format_options.keyboard_gap.join(unused_l)
            unused_s = "{} {}".format(unused_s, Lang.lang(plugin, "play_keyboard_unused"))

        out_s = None
        if out_l:
            out_s = format_options.keyboard_gap.join(out_l)
            if not format_options.keyboard_monospace and format_options.keyboard_strike:
                out_s = "~~{}~~".format(out_s)
            out_s = "{} {}".format(out_s, Lang.lang(plugin, "play_keyboard_out"))

        keyboard = []
        for el in found_s, out_s, unused_s:
            if el:
                keyboard.append(el)
        keyboard = "\n".join(keyboard)

        # put things in monospace
        if format_options.monospace:
            if format_options.keyboard_monospace:
                r = "```\n{}\n\n{}\n```".format(r, keyboard)
            else:
                r = "```\n{}\n```\n{}\n".format(r, keyboard)
        else:
            if format_options.keyboard_monospace:
                r = "{}\n\n```\n{}\n```".format(r, keyboard)
            else:
                r = "{}\n\n{}".format(r, keyboard)

    elif format_options.monospace:
        r = "```\n{}\n```".format(r)

    return r
