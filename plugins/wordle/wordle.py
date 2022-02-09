import logging
from typing import Optional, Dict

from nextcord.ext import commands

from base.configurable import BasePlugin
from base.data import Config, Lang, Storage
from botutils.converters import get_best_username as gbu
from botutils.permchecks import check_admin_access
from botutils.setter import ConfigSetter
from botutils.stringutils import table, paginate, format_number
from botutils.utils import helpstring_helper, add_reaction, log_exception
from services.helpsys import DefaultCategories

from plugins.wordle.game import Game, Correctness, WORDLENGTH
from plugins.wordle.naivesolver import NaiveSolver
from plugins.wordle.utils import format_guess
from plugins.wordle.wordlist import fetch_powerlanguage_impl, WordList
from plugins.wordle.gamehandler import Mothership, AlreadyRunning

BASE_CONFIG = {
    "default_wordlist": [str, "en"],
    "format_guess_monospace": [bool, False],
    "format_guess_include_word": [bool, False],
    "format_guess_vertical": [bool, False],
    "format_guess_history": [bool, False],
    "format_guess_keyboard": [bool, False],
    "format_guess_keyboard_gap": [str, ""],
    "format_guess_keyboard_strike": [bool, True],
    "format_guess_keyboard_monospace": [bool, False],
    "format_guess_uppercase": [bool, True]
}


class Plugin(BasePlugin, name="Wordle"):
    WORDLIST_CONTAINER = "wordlists"
    WORDLIST_KEY = "lists"

    def __init__(self):
        super().__init__()
        Config().bot.register(self, category=DefaultCategories.GAMES)
        self.logger = logging.getLogger(__name__)
        self.wordlists: Dict[str, WordList] = {}

        self.config_setter = ConfigSetter(self, BASE_CONFIG)
        self.deserialize_wordlists()
        self.mothership = Mothership(self)

    @commands.Cog.listener()
    async def on_message(self, message):
        await self.mothership.on_message(message)

    def get_config(self, key):
        return Config.get(self).get(key, BASE_CONFIG[key][1])

    def default_storage(self, container=None):
        return {}

    def default_config(self, container=None):
        return {}

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def deserialize_wordlists(self):
        """
        Deserializes all wordlists from storage and fills self.wordlists.
        """
        self.logger.debug("Loading wordlists")
        wls = Storage.get(self, container=self.WORDLIST_CONTAINER)
        for key, wl in wls.items():
            self.logger.debug("Reading wordlist %s", key)
            self.wordlists[key] = WordList.deserialize(wl)

    def save_wordlists(self):
        """
        Writes all wordlists into storage.
        """
        r = {}
        for key, wl in self.wordlists.items():
            r[key] = wl.serialize()
        Storage.set(self, r, container=self.WORDLIST_CONTAINER)
        Storage.save(self, container=self.WORDLIST_CONTAINER)

    @commands.group(name="wordle", invoke_without_command=True)
    async def cmd_wordle(self, ctx):
        await Config().bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd_wordle.command(name="set", aliases=["config"], hidden=True)
    async def cmd_set(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        await self.config_setter.set_cmd(ctx, key, value)

    @cmd_wordle.command(name="wordlist")
    async def cmd_wordlist(self, ctx, name: Optional[str] = None, url: Optional[str] = None):
        if name and not url:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "missing_argument"))
            return

        # list lists
        if not name:
            msgs = []
            for wlname, wl in self.wordlists.items():
                t = (
                    (Lang.lang(self, "wordlist_url"), wl.url),
                    (Lang.lang(self, "wordlist_parser"), wl.parser.value),
                    (Lang.lang(self, "wordlist_solutions"), len(wl.solutions)),
                    (Lang.lang(self, "wordlist_complement"), len(wl.complement)),
                    (Lang.lang(self, "wordlist_total"), len(wl.solutions) + len(wl.complement)),
                )
                msgs.append("**{}**\n{}".format(wlname, table(t)))
            if not msgs:
                msgs.append(Lang.lang(self, "wordlist_no_lists"))
            for msg in paginate(msgs, prefix=Lang.lang(self, "wordlist_list_title") + "\n", delimiter="\n\n"):
                await ctx.send(msg)
            return

        # add list
        if name in self.wordlists:
            await add_reaction(ctx.message, Lang.CMDERROR)
            ctx.send(Lang.lang(self, "wordlist_exists", name))
            return
        try:
            wl = await fetch_powerlanguage_impl(url)
        except Exception as e:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "parse_error"))
            await log_exception(e, context=ctx, title=":x: Wordle word list parse error")
            return
        self.wordlists[name] = wl
        self.save_wordlists()
        await ctx.send(wl)

    @cmd_wordle.command(name="play")
    async def cmd_wordle_play(self, ctx, wordlist: Optional[str] = None):
        solution = None
        default = self.get_config("default_wordlist")
        if not wordlist:
            wordlist = default

        if wordlist not in self.wordlists:
            # try to turn it into a game word argument
            if wordlist and len(wordlist) == WORDLENGTH and wordlist in self.wordlists[default]:
                solution = wordlist
                wordlist = default
            else:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "wordlist_not_found"))

        wordlist = self.wordlists[wordlist]

        try:
            instance = await self.mothership.spawn(self, wordlist, ctx.author, ctx.channel, solution=solution)
            if not instance.respawned:
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
        except AlreadyRunning:
            await ctx.send(Lang.lang(self, "play_error_game_exists", gbu(ctx.author), ctx.channel.mention))

    @cmd_wordle.command(name="list")
    async def cmd_wordle_list(self, ctx):
        msgs = []
        for i in range(len(self.mothership.instances)):
            el = self.mothership.instances[i]
            p = gbu(el.player)
            g = el.game
            msgs.append("**#{}** {} in {}, {}/{}".format(i + 1, p, el.channel.mention, len(g.guesses), g.max_tries))
        for msg in paginate(msgs, prefix="_ _"):
            await ctx.send(msg)

    @cmd_wordle.command(name="stop")
    async def cmd_wordle_stop(self, ctx, wid: Optional[int] = None):
        # find instance
        instance = None
        if wid is not None:
            try:
                instance = self.mothership.instances[wid-1]
            except IndexError:
                pass

            # permission check
            if not check_admin_access(ctx.message.author) and ctx.message.author != instance.player:
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                return

        else:
            for el in self.mothership.instances:
                if el.player == ctx.author and el.channel == ctx.channel:
                    instance = el
                    break

        if instance is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "wordle_not_found"))
            return

        self.mothership.deregister(instance)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_wordle.command(name="solve")
    async def cmd_wordle_solve(self, ctx, word: Optional[str]):
        wl_key = self.get_config("default_wordlist")
        wordlist = self.wordlists.get(wl_key, None)
        if wordlist is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "wordlist_not_found", wl_key))
            return

        if word is None:
            word = wordlist.random_solution()
            await ctx.send("Guessing {}".format(word))
        else:
            if word not in wordlist:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "not_in_wordlist", wl_key))
                return

        game = Game(wordlist, word)
        NaiveSolver(game).solve()

        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send(format_guess(self, game, game.guesses[-1], done=True, history=True))

    @cmd_wordle.command(name="solvetest", hidden=True)
    async def cmd_wordle_solvetest(self, ctx, quantity: int = 100):
        wl_key = self.get_config("default_wordlist")
        wordlist = self.wordlists.get(wl_key, None)
        if wordlist is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "wordlist_not_found", wl_key))
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

        results = {}
        failures = 0
        total_score = 0
        for i in range(0, 7):
            results[i] = 0

        async with ctx.typing():
            for _ in range(quantity):
                game = Game(wordlist)
                try:
                    NaiveSolver(game).solve()
                except RuntimeError:
                    failures += 1
                    continue

                result = game.done
                assert result != Correctness.PARTIALLY
                if result == Correctness.CORRECT:
                    results[len(game.guesses)] += 1
                    total_score += 7 - len(game.guesses)
                else:
                    results[0] += 1

            msgs = ["{} Games played; results:".format(quantity)]
            for key, result in results.items():
                key = "X" if key == 0 else key
                msgs.append("{}/6: {}".format(key, result))
            if failures > 0:
                msgs.append("Alg failures: {}".format(failures))
            msgs.append("total score: {}".format(format_number(total_score / quantity)))

            for msg in paginate(msgs, prefix="```", suffix="```"):
                await ctx.send(msg)
