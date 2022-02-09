from base.data import Lang

from plugins.wordle.game import Game, Guess, WORDLENGTH, Correctness


ICONS = {
    Correctness.CORRECT: "🟩",
    Correctness.PARTIALLY: "🟨",
    Correctness.INCORRECT: "⬛",
}


def format_guess(plugin, game: Game, guess: Guess, done: bool = False, history: bool = False) -> str:
    """
    Formats the output string for a guess.

    :param plugin: Plugin ref
    :param game: Game that is being solved
    :param guess: Guess instance that is to be formatted
    :param done: if set to True, keyboard is strictly omitted
    :param history: if set to True, shows all the guesses so far
    :return: formatted string
    """
    mono = plugin.get_config("format_guess_monospace")
    uppercase = plugin.get_config("format_guess_uppercase")
    show_word = plugin.get_config("format_guess_include_word")

    # format correctness
    guesses = game.guesses if history else [guess]
    r = []

    # vertical
    if plugin.get_config("format_guess_vertical"):
        for i in range(WORDLENGTH):
            line = []
            for el in guesses:
                word = el.word.upper() if uppercase else el.word
                if show_word:
                    line.append("{} {}".format(word[i], ICONS[el.correctness[i]]))
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
    if not done and plugin.get_config("format_guess_keyboard"):
        kb_mono = plugin.get_config("format_guess_keyboard_monospace")
        found_l, out_l, unused_l = game.alphabet(uppercase=uppercase)
        delimiter = plugin.get_config("format_guess_keyboard_gap")

        found_s = None
        if found_l:
            found_s = delimiter.join(found_l)
            found_s = "{} {}".format(found_s, Lang.lang(plugin, "play_keyboard_found"))

        unused_s = None
        if unused_l:
            unused_s = delimiter.join(unused_l)
            unused_s = "{} {}".format(unused_s, Lang.lang(plugin, "play_keyboard_unused"))

        out_s = None
        if out_l:
            out_s = delimiter.join(out_l)
            if not kb_mono and plugin.get_config("format_guess_keyboard_strike"):
                out_s = "~~{}~~".format(out_s)
            out_s = "{} {}".format(out_s, Lang.lang(plugin, "play_keyboard_out"))

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
                r = "```\n{}\n```\n{}\n".format(r, keyboard)
        else:
            if kb_mono:
                r = "{}\n\n```\n{}\n```".format(r, keyboard)
            else:
                r = "{}\n\n{}".format(r, keyboard)

    elif mono:
        r = "```\n{}\n```".format(r)

    return r
