import logging
import warnings
from enum import Enum

import discord
from discord.ext import commands
from discord.errors import HTTPException

from base import BasePlugin
from conf import Storage, Lang, Config
from subsystems import help
from botutils import permchecks

from plugins.quiz.controllers import RushQuizController, PointsQuizController
from plugins.quiz.quizapis import quizapis, opentdb
from plugins.quiz.base import Difficulty
from plugins.quiz.utils import get_best_username
from plugins.quiz.migrations import migration

jsonify = {
    "timeout": 20,  # answering timeout in minutes; not impl yet TODO
    "timeout_warning": 2,  # warning time before timeout in minutes
    "questions_limit": 25,
    "questions_default": 10,
    "default_category": -1,
    "question_cooldown": 5,
    "channel_blacklist": [],
    "points_quiz_register_timeout": 1 * 60,
    "points_quiz_question_timeout": 20,  # warning after this value, actual timeout after 1.5*this value
    "ranked_min_players": 4,
    "ranked_min_questions": 7,
    "ranked_register_additional_tries": 2,
    "emoji_in_pose": True,
    "channel_mapping": {
        706125113728172084: "any",
        716683335778173048: "politics",
        706128206687895552: "games",
        706129681790795796: "sports",
        706129811382337566: "tv",
        706129915405271123: "music",
        706130284252364811: "computer",
    }
}

h_help = "A trivia kwiss"
h_description = "Starts a kwiss.\n\n" \
                "Subcommands:\n" \
                "!kwiss status - Gets information about the kwiss currently running in this channel.\n" \
                "!kwiss stop - Stops the currently running kwiss. Only for kwiss starter and botmasters.\n" \
                "!kwiss categories - List of categories.\n" \
                "!kwiss emoji <emoji> - Sets your prefix emoji.\n" \
                "!kwiss ladder - Shows the ranked ladder.\n" \
                "!kwiss del <user> - Removes a user from the ranked ladder. Admins only.\n" \
                "!kwiss question - Information about the current question.\n\n" \
                "Optional arguments to start a kwiss (in any order):\n" \
                "mode - Game mode. One out of points, rush." \
                "category - one out of !kwiss category\n" \
                "difficulty - one out of any, easy, medium, hard\n" \
                "question count - number that determines how many questions are to be posed\n" \
                "ranked - include this to start a ranked kwiss\n" \
                "gecki - Gecki participates (only works in points mode)\n" \
                "Example: !kwiss 5 tv hard gecki\n\n" \
                "Points game mode:\n" \
                "Each question is answered by all players. The players earn points depending on how many questions " \
                "they answered correctly. The player who earned the most points wins.\n\n" \
                "Rush game mode:\n" \
                "The player who is the fastest to answer correctly wins the question. The player who answers " \
                "the most questions correctly wins.\n\n" \
                "Ranked\n" \
                "To start a kwiss that counts for the eternal global ladder, use the argument \"ranked\". " \
                "Ranked kwisses are constrained in most kwiss parameters (especially mode and difficulty)."
h_usage = "[<mode> <question count> <difficulty> <category> <ranked> <debug>]"


class QuizInitError(Exception):
    def __init__(self, plugin, msg_id, *args):
        super().__init__(Lang.lang(plugin, msg_id, *args))


class SubCommandEncountered(Exception):
    def __init__(self, callback, args):
        super().__init__()
        self.callback = callback
        self.args = args


class Methods(Enum):
    START = "start"
    STOP = "stop"
    SCORE = "score"
    PAUSE = "pause"
    RESUME = "resume"
    STATUS = "status"


class Plugin(BasePlugin, name="A trivia kwiss"):
    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.controllers = {}
        self.registered_subcommands = {}
        self.config = jsonify

        self.default_controller = PointsQuizController
        self.defaults = {
            "quizapi": quizapis["opentdb"],
            "questions": self.config["questions_default"],
            "method": Methods.START,
            "category": None,
            "difficulty": Difficulty.EASY,
            "ranked": False,
            "gecki": False,
            "debug": False,
            "subcommand": None,
        }

        self.controller_mapping = {
            RushQuizController: ["rush", "race", "wtia"],
            PointsQuizController: ["points"],
        }

        # Documented subcommands
        self.register_subcommand(None, "question", self.cmd_question)

        # Undocumented subcommands
        self.register_subcommand(None, "info", self.cmd_info)

        super().__init__(bot)
        bot.register(self, help.DefaultCategories.GAMES)

        # Migrate data if necessary
        migration(self, self.logger)

        @commands.Cog.listener()
        async def on_message(msg):
            quiz = self.get_controller(msg.channel)
            if quiz:
                await quiz.on_message(msg)

    def default_storage(self):
        return {
            "emoji": {},
            "ladder": {},
        }

    """
    Help
    """
    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.name))

    def command_description(self, command):
        return Lang.lang(self, "desc_{}".format(command.name))

    def sort_subcommands(self, ctx, cmd, subcommands):
        order = [
            "status",
            "score",
            "stop",
            "emoji",
            "ladder",
            "categories",
            "del",
            "question",
        ]
        todel = []
        for i in range(len(order) - 1, -1, -1):
            found = False
            for cmd in subcommands:
                if cmd.name == order[i]:
                    order[i] = cmd
                    found = True
                    break
            if not found:
                todel.append(i)

        for i in todel:
            del order[i]

        return order

    """
    Commands
    """
    @commands.group(name="kwiss",
                    help=h_help,
                    description=h_description,
                    usage=h_usage,
                    invoke_without_command=True)
    async def kwiss(self, ctx, *args):
        """
        !kwiss command
        """
        self.logger.debug("Caught kwiss cmd")
        channel = ctx.channel
        try:
            controller_class, args = self.parse_args(channel, args)
        except QuizInitError as e:
            # Parse Error
            await ctx.send(str(e))
            return

        # Subcommand
        except SubCommandEncountered as subcmd:
            self.logger.debug("Calling subcommand: {}, {}".format(subcmd.callback, subcmd.args))
            await subcmd.callback(ctx, *subcmd.args)
            return

        err = self.args_combination_check(controller_class, args)
        if err is not None:
            args = []
            if err == "ranked_playercount":
                args = (self.config["ranked_min_participants"],)
            if err == "ranked_questioncount":
                args = (self.config["ranked_min_questions"],)
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, err, *args))
            return

        # Look for existing quiz
        method = args["method"]
        if method == Methods.START and self.get_controller(channel):
            await ctx.message.add_reaction(Lang.CMDERROR)
            raise QuizInitError(self, "existing_quiz")

        # Starting a new quiz
        assert method == Methods.START
        await ctx.message.add_reaction(Lang.EMOJI["success"])
        async with ctx.typing():
            quiz_controller = controller_class(self,
                                               self.config,
                                               args["quizapi"],
                                               ctx.channel,
                                               ctx.message.author,
                                               category=args["category"],
                                               question_count=args["questions"],
                                               difficulty=args["difficulty"],
                                               debug=args["debug"],
                                               ranked=args["ranked"],
                                               gecki=args["gecki"])
            self.controllers[channel] = quiz_controller
            self.logger.debug("Registered quiz controller {} in channel {}".format(quiz_controller, ctx.channel))
        await quiz_controller.status(ctx.message)
        await quiz_controller.start(ctx.message)

    @kwiss.command(name="status")
    async def cmd_status(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "status_no_quiz"))
        else:
            await controller.status(ctx.message)

    @kwiss.command(name="score")
    async def cmd_score(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
        else:
            await ctx.send(embed=controller.score.embed())

    @kwiss.command(name="stop")
    async def cmd_stop(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
        elif permchecks.check_full_access(ctx.message.author) or controller.requester == ctx.message.author:
            await self.abort_quiz(ctx.channel, ctx.message)
        else:
            await ctx.message.add_reaction(Lang.CMDNOPERMISSIONS)

    @kwiss.command(name="emoji")
    async def cmd_emoji(self, ctx, *args):
        # Delete emoji
        if len(args) == 0:
            if ctx.message.author.id in Storage().get(self)["emoji"]:
                del Storage().get(self)["emoji"][ctx.message.author.id]
                await ctx.message.add_reaction(Lang.CMDSUCCESS)
                Storage().save(self)
            else:
                await ctx.message.add_reaction(Lang.CMDNOCHANGE)
            return

        # Too many arguments
        if len(args) != 1:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        emoji = args[0]
        try:
            await ctx.message.add_reaction(emoji)
        except HTTPException:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        Storage().get(self)["emoji"][ctx.message.author.id] = emoji
        Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @kwiss.command(name="ladder")
    async def cmd_ladder(self, ctx):
        embed = discord.Embed()
        entries = {}
        ladder = Storage().get(self)["ladder"]
        for uid in ladder:
            member = discord.utils.get(ctx.guild.members, id=uid)
            points = ladder[uid]["points"]
            games_played = ladder[uid]["games_played"]
            if points not in entries:
                entries[points] = [(member, games_played)]
            else:
                entries[points].append((member, games_played))

        values = []
        keys = sorted(entries.keys(), reverse=True)
        place = 0
        for el in keys:
            place += 1
            for user, games_played in entries[el]:
                uname = get_best_username(Storage().get(self), user)
                values.append(Lang.lang(self, "ladder_entry", place, el, uname, games_played))

        if len(values) == 0:
            await ctx.send("So far, nobody is on the ladder.")
            return

        embed.add_field(name="Ladder:", value="\n".join(values))
        embed.set_footer(text=Lang.lang(self, "ladder_suffix"))
        await ctx.send(embed=embed)

    @kwiss.command(name="categories", aliases=["cat", "cats", "category"])
    async def cmd_catlist(self, ctx, *args):
        embed = discord.Embed(title="Categories:")
        s = []
        for el in opentdb["cat_mapping"]:
            cat = el["names"]
            s.append("**{}**: {}".format(cat[0], cat[1]))
        embed.add_field(name="Name: Command", value="\n".join(s))
        await ctx.send(embed=embed)

    @kwiss.command(name="del", usage="<user>")
    async def cmd_del(self, ctx, *args):
        if len(args) != 1:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return
        if not permchecks.check_full_access(ctx.message.author):
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        try:
            user = await commands.MemberConverter().convert(ctx, args[0])
        except (commands.CommandError, IndexError):
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        ladder = Storage().get(self)["ladder"]
        if user.id in ladder:
            del ladder[user.id]
            Storage().save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        else:
            await ctx.message.add_reaction(Lang.CMDNOCHANGE)

    @kwiss.command(name="question")
    async def cmd_question(self, ctx, *args):
        if len(args) != 1:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        controller = self.get_controller(ctx.channel)
        if controller is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        embed = controller.quizapi.current_question().embed(emoji=True, info=True)
        await ctx.channel.send(embed=embed)

    @kwiss.command(name="info", hidden=True)
    async def cmd_info(self, ctx, *args):
        args = args[1:]
        controller, args = self.parse_args(ctx.channel, args, subcommands=False)
        await ctx.send(args["quizapi"].info(**args))

    """
    Interface
    """
    def update_ladder(self, member, points):
        ladder = Storage().get(self)["ladder"]
        if member.id in ladder:
            ladder[member.id]["points"] = int(round(ladder[member.id]["points"] * 3/4 + points * 1/4))
            ladder[member.id]["games_played"] += 1
        else:
            ladder[member.id] = {
                "points": int(round(points * 3/4)),
                "games_played": 1,
            }
        Storage().save(self)

    def register_subcommand(self, channel, subcommand, callback):
        """
        Registers a subcommand. If the subcommand is found in a command, the callback coroutine is called.
        :param channel: Channel in which the registering quiz takes place. None for global.
        :param subcommand: subcommand string that is looked for in incoming commands. Case-insensitive.
        :param callback: Coroutine of the type f(ctx, *args); is called with the context object and every arg, including
        the subcommand itself and excluding the main command ("kwiss")
        """
        self.logger.debug("Subcommand registered: {}; callback: {}".format(subcommand, callback))
        subcommand = subcommand.lower()
        found = False
        for el in self.registered_subcommands:
            if el == channel:
                found = True
                if subcommand in self.registered_subcommands[channel]:
                    warnings.warn(RuntimeWarning("Subcommand was registered twice: {}".format(subcommand)))
                self.registered_subcommands[channel][subcommand] = callback
                break

        if not found:
            self.registered_subcommands[channel] = {
                subcommand: callback
            }

    def get_controller(self, channel):
        """
        Retrieves the running quiz controller in a channel.
        :param channel: Channel that is checked for.
        :return: BaseQuizController object that is running in channel. None if no quiz is running in channel.
        """
        if channel in self.controllers:
            return self.controllers[channel]
        return None

    async def abort_quiz(self, channel, msg):
        """
        Called on !kwiss stop. It is assumed that there is a quiz in channel.
        :param channel: channel that the abort was requested in.
        :param msg: Message object
        """
        controller = self.controllers[channel]
        await controller.abort(msg)

    def end_quiz(self, channel):
        """
        Cleans up the quiz.
        :param channel: channel that the quiz is taking place in
        :return: (End message, score embed)
        """
        self.logger.debug("Cleaning up quiz in channel {}.".format(channel))
        if channel not in self.controllers:
            assert False, "Channel not in controller list"
        del self.controllers[channel]

    """
    Parse arguments
    """
    def args_combination_check(self, controller, args):
        """
        Checks for argument combination constraints.
        :param controller: Quiz controller class
        :param args: args dict
        :return: lang code for error msg, None if the arg combination is okay
        """
        # Ranked constraints
        if args["ranked"] and not args["debug"]:
            if controller != self.default_controller:
                return "ranked_constraints"
            if args["category"] != self.defaults["category"]:
                return "ranked_constraints"
            if args["difficulty"] != self.defaults["difficulty"]:
                return "ranked_constraints"
            if args["questions"] < self.config["ranked_min_questions"]:
                return "ranked_questioncount"
            if not Config().DEBUG_MODE and args["gecki"]:
                return "ranked_gecki"
        return None

    def parse_args(self, channel, args, subcommands=True):
        """
        Parses the arguments given to the quiz command and fills in defaults if necessary.
        :param channel: Channel in which the command was issued
        :param args: argument list
        :param subcommands: Whether to fish for subcommands
        :return: Dict with the parsed arguments
        """
        self.logger.debug("Parsing args: {}".format(args))
        found = {el: False for el in self.defaults}
        parsed = self.defaults.copy()
        controller = self.default_controller
        controller_found = False

        # Fish for subcommand
        subcmd = None
        for el in self.registered_subcommands:
            if not subcommands:
                break
            if el is not None and el != channel:
                continue
            for arg in args:
                if arg in self.registered_subcommands[el]:
                    if subcmd is not None:
                        raise QuizInitError(self, "duplicate_subcmd_arg")
                    subcmd = self.registered_subcommands[el][arg]
        if subcmd is not None:
            raise SubCommandEncountered(subcmd, args)

        # Parse regular arguments
        for arg in args:
            arg = arg.lower()

            # Question count
            try:
                arg = int(arg)
                if found["questions"]:
                    raise QuizInitError(self, "duplicate_count_arg")
                if arg > self.config["questions_limit"]:
                    raise QuizInitError(self, "too_many_questions", arg)
                parsed["questions"] = arg
                found["questions"] = True
                continue
            except (ValueError, TypeError):
                pass

            # Quiz database
            quizapi_found = False
            for db in quizapis:
                if arg == db:
                    if found["quizapi"]:
                        raise QuizInitError(self, "duplicate_db_arg")
                    parsed["quizapi"] = quizapis[db]
                    found["quizapi"] = True
                    quizapi_found = True
                    continue
            if quizapi_found:
                continue

            # method
            try:
                method = Methods(arg)
                if found["method"]:
                    raise QuizInitError(self, "duplicate_method_arg")
                parsed["method"] = method
                found["method"] = True
                continue
            except ValueError:
                pass

            # difficulty
            try:
                difficulty = Difficulty(arg)
                if found["difficulty"]:
                    raise QuizInitError(self, "duplicate_difficulty_arg")
                parsed["difficulty"] = difficulty
                found["difficulty"] = True
                continue
            except ValueError:
                pass

            # controller
            for el in self.controller_mapping:
                if arg in self.controller_mapping[el]:
                    if controller_found:
                        raise QuizInitError(self, "duplicate_controller_arg")
                    controller = el
                    controller_found = True
                    break
            if controller_found:
                continue

            # ranked
            if arg == "ranked":
                parsed["ranked"] = True
                found["ranked"] = True
                continue

            # gecki
            if arg == "gecki":
                parsed["gecki"] = True
                found["gecki"] = True
                continue

            # debug
            if arg == "debug":
                parsed["debug"] = True
                found["debug"] = True
                continue

            # category
            found_cat = False
            for api in quizapis.values():
                cat = api.category_key(arg)
                if cat is not None:
                    if found["category"]:
                        raise QuizInitError(self, "dupiclate_cat_arg")
                    parsed["category"] = arg
                    found["category"] = True
                    found_cat = True
                    break
            if found_cat:
                continue

            raise QuizInitError(self, "unknown_arg", arg)

        # check if quizapi supports category
        if found["quizapi"] or found["category"]:  # todo improve this check
            catkey = parsed["quizapi"].category_key(parsed["category"])
            if catkey is None:
                apiname = None
                for api in quizapis:
                    if quizapis[api] == parsed["quizapi"]:
                        apiname = api
                        break
                assert apiname is not None
                raise QuizInitError(self, "category_not_supported", apiname, parsed["category"])
            else:
                parsed["category"] = catkey

        self.logger.debug("Parsed kwiss args: {}".format(parsed))
        return controller, parsed
