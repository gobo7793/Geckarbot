import logging
from datetime import date
from typing import Optional, Dict, Type, List

from nextcord import DMChannel
from nextcord.ext import commands

from base.configurable import BasePlugin
from base.data import Config, Lang, Storage
from botutils.converters import get_best_username as gbu, serialize_channel, deserialize_channel
from botutils.permchecks import check_admin_access
from botutils.setter import ConfigSetter
from botutils.stringutils import table, paginate, format_number
from botutils.utils import helpstring_helper, add_reaction, log_exception, execute_anything_sync
from services.helpsys import DefaultCategories

from plugins.wordle.game import Game, Correctness, WORDLENGTH, HelpingSolver
from plugins.wordle.naivesolver import NaiveSolver
from plugins.wordle.dicesolver import DiceSolver
from plugins.wordle.utils import format_guess, format_daily
from plugins.wordle.wordlist import WordList, Parsers
from plugins.wordle.gamehandler import Mothership
from services.timers import timedict

BASE_CONFIG = {
    "default_wordlist": [str, "en"],
    "default_solver": [str, "naive"],
    "format_guess_monospace": [bool, False],
    "format_guess_include_word": [bool, False],
    "format_guess_vertical": [bool, False],
    "format_guess_history": [bool, False],
    "format_guess_letter_gap": [str, ""],
    "format_guess_guess_gap": [str, "\n"],
    "format_guess_correctness_gap": [str, ""],
    "format_guess_keyboard": [bool, False],
    "format_guess_keyboard_gap": [str, ""],
    "format_guess_keyboard_strike": [bool, True],
    "format_guess_keyboard_monospace": [bool, False],
    "format_guess_uppercase": [bool, True],
    "format_guess_letter_emoji": [bool, False]
}


SOLVERS: Dict[str, Type[HelpingSolver]] = {
    "naive": NaiveSolver,
    "dice": DiceSolver
}


class WordlistNotFound(Exception):
    """
    Raised by commands that take a wordlist name as an argument.
    """
    def __init__(self, plugin, wordlist: str):
        self.plugin = plugin
        self.wordlist = wordlist

    async def default(self, ctx):
        await add_reaction(ctx.message, Lang.CMDERROR)
        await ctx.send(Lang.lang(self.plugin, "wordlist_not_found", self.wordlist))


class Summon:
    """
    Represents a summoned daily.
    """
    def __init__(self, plugin, channel, wordlist: str):
        self.plugin = plugin
        self.channel = channel
        self.wordlist_name = wordlist
        self.wordlist = self.plugin.get_wordlist(wordlist)

        self.last_game_ts = None
        self.last_game = None

    def serialize(self) -> dict:
        for key, wl in self.plugin.wordlists.items():
            if wl == self.wordlist:
                return {
                    "wordlist": key,
                    "channel": serialize_channel(self.channel),
                }

    @classmethod
    async def deserialize(cls, plugin, d):
        return cls(plugin, await deserialize_channel(d["channel"]), d["wordlist"])

    async def fire(self):
        p = Parsers.get(self.wordlist.parser.value)
        dailyword, epoch_index = await p.fetch_daily(self.wordlist.url)
        self.last_game_ts = date.today()
        self.last_game = Game(self.wordlist, dailyword)
        self.last_game_ts = date.today()
        SOLVERS[self.plugin.get_config("default_solver")](self.last_game).solve()
        await self.channel.send(format_daily(self.plugin, Parsers.NYTIMES, self.last_game, epoch_index))

    async def show(self, ctx):
        await ctx.author.send(format_guess(self.plugin, self.last_game, self.last_game.guesses[-1], done=True, history=True))


class Plugin(BasePlugin, name="Wordle"):
    WORDLIST_CONTAINER = "wordlists"
    WORDLIST_KEY = "lists"

    def __init__(self):
        super().__init__()
        Config().bot.register(self, category=DefaultCategories.GAMES)
        self.logger = logging.getLogger(__name__)
        self.wordlists: Dict[str, WordList] = {}
        self.summons: List[Summon] = []
        self.summon_job = None
        self.migrate()

        self.config_setter = ConfigSetter(self, BASE_CONFIG)
        self.deserialize_wordlists()
        execute_anything_sync(self.build_summons())
        self.mothership = Mothership(self)

    @commands.Cog.listener()
    async def on_message(self, message):
        await self.mothership.on_message(message)

    def get_config(self, key):
        return Config.get(self).get(key, BASE_CONFIG[key][1])

    def default_storage(self, container=None):
        return {
            "version": 0,
        }

    def default_config(self, container=None):
        if container is None:
            return {
                "version": 0,
            }
        else:
            return {}

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def migrate(self):
        wls = Storage.get(self, container=self.WORDLIST_CONTAINER)
        for wl in wls.values():
            if wl["parser"] == "powerlanguage":
                wl["parser"] = "nytimes"
                wl["url"] = "https://www.nytimes.com/games/wordle/index.html"
        Storage.save(self, container=self.WORDLIST_CONTAINER)

        # rename config keys
        cfg = Config.get(self)
        if "version" not in cfg:
            cfg["version"] = 0
            if "format_guess_word_gap" in cfg:
                cfg["format_guess_letter_gap"] = cfg["format_guess_word_gap"]
                del cfg["format_guess_word_gap"]
            if "format_guess_result_gap" in cfg:
                cfg["format_guess_correctness_gap"] = cfg["format_guess_result_gap"]
                del cfg["format_guess_result_gap"]
            Config.save(self)

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

    def get_wordlist(self, wordlist: Optional[str]) -> WordList:
        """
        Returns the word list `wordlist`, default if `wordlist` is None.
        :param wordlist: wordlist name; None for default
        :return: WordList that was found
        :raises WordlistNotFound: If there is no such wordlist
        """
        if wordlist is None:
            wordlist = self.get_config("default_wordlist")

        try:
            return self.wordlists[wordlist]
        except KeyError:
            raise WordlistNotFound(self, wordlist)

    async def summon_job_coro(self, _):
        for summon in self.summons:
            await summon.fire()

    async def build_summons(self):
        """
        Fills self.summons and starts the job.
        """
        summons = Storage.get(self).get("summons", [])
        for d in summons:
            self.summons.append(await Summon.deserialize(self, d))

        td = timedict(hour=0, minute=10)
        self.summon_job = Config().bot.timers.schedule(self.summon_job_coro, td)

    def save_summons(self):
        """
        Saves self.summons to storage.
        """
        s = Storage.get(self)
        s["summons"] = []

        for el in self.summons:
            s["summons"].append(el.serialize())
        Storage.save(self)

    @commands.group(name="wordle", invoke_without_command=True)
    async def cmd_wordle(self, ctx, wordlist: Optional[str] = None):
        await self.cmd_wordle_play(ctx, wordlist)

    @cmd_wordle.command(name="set", aliases=["config"], hidden=True)
    async def cmd_set(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        # specifics
        if key == "default_solver":
            if value not in SOLVERS:
                await ctx.send("Invalid solver: {}".format(value))
                await add_reaction(ctx.message, Lang.CMDERROR)
                return

        await self.config_setter.set_cmd(ctx, key, value)

    @cmd_wordle.command(name="wordlist")
    async def cmd_wordlist(self, ctx,
                           name: Optional[str] = None, url: Optional[str] = None, parser: Optional[str] = None):
        # pylint: disable=broad-except
        if name and not parser:
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
            parser = Parsers.get(parser)
            wl = await parser.fetch(url)
        except Exception as e:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "parse_error"))
            await log_exception(e, context=ctx, title=":x: Wordle word list parse error")
            return
        self.wordlists[name] = wl
        self.save_wordlists()
        await ctx.send(wl)

    @cmd_wordle.group(name="play", invoke_without_command=True)
    async def cmd_wordle_play(self, ctx, wordlist: Optional[str] = None):
        solution = None

        wlname = wordlist
        try:
            wordlist = self.get_wordlist(wlname)
        except WordlistNotFound as e:
            # Try to interpret the wordlist arg as the solution word
            default = self.get_wordlist(None)
            if wlname and len(wlname) == WORDLENGTH and wlname in default:
                solution = wlname
                wordlist = default
            else:
                await e.default(ctx)
                return

        solver = SOLVERS[self.get_config("default_solver")]

        already_running = await self.mothership.catch_respawn(ctx.author, ctx.channel)
        if already_running is None:
            await self.mothership.spawn(self, wordlist, ctx.author, ctx.channel, solver, solution=solution)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_wordle_play.command(name="suggest")
    async def cmd_wordle_play_suggest(self, ctx):
        instance = self.mothership.get_instance(ctx.channel, ctx.author)
        if instance is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "wordle_not_found"))
            return

        await instance.suggest()

    @cmd_wordle.command(name="suggest")
    async def cmd_wordle_suggest(self, ctx):
        await self.cmd_wordle_play_suggest(ctx)

    @cmd_wordle.command(name="list")
    async def cmd_wordle_list(self, ctx):
        msgs = []
        for i in range(len(self.mothership.instances)):
            el = self.mothership.instances[i]
            p = gbu(el.player)
            g = el.game
            if isinstance(el.channel, DMChannel):
                chan = "DM-Channel"
            else:
                chan = el.channel.mention
            msgs.append("**#{}** {} in {}, {}/{}".format(i + 1, p, chan, len(g.guesses), g.max_tries))
        if not msgs:
            await ctx.send(Lang.lang(self, "empty_result"))
            return

        for msg in paginate(msgs, prefix="_ _"):
            await ctx.send(msg)

    @cmd_wordle.command(name="knows", aliases=["has", "is"])
    async def cmd_wordle_knows(self, ctx, word: str, wordlist: Optional[str] = None):
        try:
            wordlist = self.get_wordlist(wordlist)
        except WordlistNotFound as e:
            await e.default(ctx)
            return

        if word in wordlist:
            await ctx.send(Lang.lang(self, "knows_yes"))
        else:
            await ctx.send(Lang.lang(self, "knows_no"))

    @cmd_wordle.command(name="stop", aliases=["cancel", "kill"])
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

    @cmd_wordle.command(name="reverse")
    async def cmd_wordle_reverse(self, ctx, wordlist: Optional[str] = None):
        try:
            wordlist = self.get_wordlist(wordlist)
        except WordlistNotFound as e:
            await e.default(ctx)
            return

        solver = SOLVERS[self.get_config("default_solver")]

        already_running = await self.mothership.catch_respawn(ctx.author, ctx.channel)
        if already_running is None:
            await self.mothership.spawn_reverse(self, wordlist, ctx.author, ctx.channel, solver)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_wordle.command(name="solve")
    async def cmd_wordle_solve(self, ctx, word: Optional[str]):
        try:
            wordlist = self.get_wordlist(None)
        except WordlistNotFound as e:
            await e.default(ctx)
            return

        if word is None:
            word = wordlist.random_solution()
            await ctx.send("Guessing {}".format(word))
        else:
            if word not in wordlist:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "not_in_wordlist", self.get_config("default_wordlist")))
                return

        game = Game(wordlist, word)
        if word is None:
            game.set_random_solution()
        SOLVERS[self.get_config("default_solver")](game).solve()

        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send(format_guess(self, game, game.guesses[-1], done=True, history=True))

    @cmd_wordle.command(name="solvetest", hidden=True)
    async def cmd_wordle_solvetest(self, ctx, quantity: int = 100):
        try:
            wordlist = self.get_wordlist(None)
        except WordlistNotFound as e:
            await e.default(ctx)
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

        results = {}
        alg_failures = []
        failed_games = []
        total_score = 0
        for i in range(0, 7):
            results[i] = 0

        async with ctx.typing():
            for i in range(quantity):
                self.logger.debug("Solvetest: game #%s", i + 1)
                game = Game(wordlist)
                game.set_random_solution()
                try:
                    NaiveSolver(game).solve()
                except RuntimeError:
                    alg_failures.append(game)
                    continue

                result = game.done
                assert result != Correctness.PARTIALLY
                if result == Correctness.CORRECT:
                    results[len(game.guesses)] += 1
                    total_score += 7 - len(game.guesses)
                else:
                    failed_games.append(game)
                    results[0] += 1

            msgs = ["{} Games played; results:".format(quantity)]
            for key, result in results.items():
                key = "X" if key == 0 else key
                msgs.append("{}/6: {}".format(key, result))
            if len(alg_failures) > 0:
                msgs.append("Alg failures: {}".format(len(alg_failures)))
            sr = format_number(100 * (quantity - results[0]) / quantity, decplaces=1)
            msgs.append("success rate: {}%".format(sr))
            msgs.append("total score: {}".format(format_number(total_score / quantity)))

            for msg in paginate(msgs, prefix="```", suffix="```"):
                await ctx.send(msg)

            # dump if debug
            if Config().bot.DEBUG_MODE:
                if len(alg_failures) > 0:
                    await ctx.send("Algorithm incomplete:")
                    for game in alg_failures:
                        await ctx.send(format_guess(self, game, game.guesses[-1], done=True, history=True))
                if len(failed_games) > 0:
                    await ctx.send("Algorithm failed (X/6):")
                    for game in failed_games:
                        await ctx.send(format_guess(self, game, game.guesses[-1], done=True, history=True))

    @cmd_wordle.group(name="summon", invoke_without_command=True)
    async def cmd_wordle_summon(self, ctx, wordlist: Optional[str]):
        wl_name = wordlist if wordlist is not None else self.get_config("default_wordlist")
        try:
            wordlist = self.get_wordlist(wordlist)
        except WordlistNotFound as e:
            await e.default(ctx)
            return

        # check if summon exists
        for summon in self.summons:
            if summon.channel == ctx.channel and summon.wordlist == wordlist:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "summon_already_exists", wl_name, ctx.channel.name))
                return

        self.summons.append(Summon(self, ctx.channel, wl_name))
        self.save_summons()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_wordle_summon.command(name="fire", hidden=True)
    async def cmd_wordle_summon_fire(self, ctx):
        await self.summon_job_coro(None)

    @cmd_wordle_summon.command(name="list")
    async def cmd_wordle_summon_list(self, ctx):
        msgs = []
        for summon in self.summons:
            msgs.append("{}: {}".format(summon.channel.name, summon.wordlist_name))
        if not msgs:
            await ctx.send(Lang.lang(self, "empty_result"))
            return

        for msg in paginate(msgs, "```", "```"):
            await ctx.send(msg)

    @cmd_wordle_summon.command(name="show", hidden=True)
    async def cmd_wordle_summon_list(self, ctx):
        for summon in self.summons:
            await summon.show(ctx)

    @cmd_wordle.command(name="dismiss", aliases=["desummon", "unsummon"])
    async def cmd_wordle_dismiss(self, ctx, wordlist: Optional[str]):
        wordlist_arg = wordlist is not None
        wordlist_name = wordlist if wordlist is not None else self.get_config("default_wordlist")
        try:
            wordlist = self.get_wordlist(wordlist)
        except WordlistNotFound as e:
            await e.default(ctx)
            return

        to_dismiss = None
        candidates = []
        for summon in self.summons:
            if summon.channel == ctx.channel:
                candidates.append(summon)

        # no summons in channel
        if not candidates:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        # unambiguous
        if len(candidates) == 1 and not wordlist_arg:
            to_dismiss = candidates[0]

        # find summon to dismiss
        else:
            for el in candidates:
                if el.wordlist == wordlist:
                    to_dismiss = el
                    break
            if to_dismiss is None:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "summon_not_found", wordlist_name))
                return

        self.summons.remove(to_dismiss)
        self.save_summons()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
