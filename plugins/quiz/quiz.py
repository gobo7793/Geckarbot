import logging
import warnings
from enum import Enum

import discord
from discord.ext import commands

import Geckarbot
from conf import Config
from botutils import permChecks

from plugins.quiz.controllers import RushQuizController, PointsQuizController
from plugins.quiz.quizapis import OpenTDBQuizAPI, quizapis
from plugins.quiz.base import Difficulty

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


class QuizInitError(Exception):
    def __init__(self, plugin, msg_id, *args):
        super().__init__(Config().lang(plugin, msg_id, *args))


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


class Plugin(Geckarbot.BasePlugin, name="A trivia kwiss"):
    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.controllers = {}
        self.registered_subcommands = {}
        self.config = jsonify

        self.default_controller = PointsQuizController
        self.defaults = {
            "impl": "opentdb",
            "questions": self.config["questions_default"],
            "method": Methods.START,
            "category": None,
            "difficulty": Difficulty.ANY,
            "debug": False,
            "subcommand": None,
        }

        self.controller_mapping = {
            RushQuizController: ["rush", "race", "wtia"],
            PointsQuizController: ["points"],
        }

        self.register_subcommand(None, "categories", self.cmd_catlist)
        self.register_subcommand(None, "emoji", self.cmd_emoji)
        self.register_subcommand(None, "ladder", self.cmd_ladder)
        self.register_subcommand(None, "question", self.cmd_question)

        super().__init__(bot)
        bot.register(self)

        @bot.listen()
        async def on_message(msg):
            quiz = self.get_controller(msg.channel)
            if quiz:
                await quiz.on_message(msg)

    def default_config(self):
        return {
            "emoji": {},
            "ladder": {},
        }

    async def cmd_catlist(self, msg, *args):
        if len(args) > 1:
            await msg.channel.send(Config().lang(self, "too_many_arguments"))
            return

        embed = discord.Embed(title="Categories:")
        s = []
        for el in OpenTDBQuizAPI.opentdb["cat_mapping"]:
            cat = el["names"]
            s.append("**{}**: {}".format(cat[0], cat[1]))
        embed.add_field(name="Name: Command", value="\n".join(s))
        await msg.channel.send(embed=embed)

    async def cmd_emoji(self, msg, *args):
        # Delete emoji
        if len(args) == 1:
            if msg.author.id in Config().get(self)["emoji"]:
                del Config().get(self)["emoji"][msg.author.id]
                await msg.add_reaction(Config().CMDSUCCESS)
                Config().save(self)
            else:
                await msg.add_reaction(Config().CMDERROR)
            return

        # Too many arguments
        if len(args) != 2:
            await msg.add_reaction(Config().CMDERROR)
            return

        emoji = args[1]
        try:
            await msg.add_reaction(emoji)
        except:
            await msg.add_reaction(Config().CMDERROR)
            return

        Config().get(self)["emoji"][msg.author.id] = emoji
        Config().save(self)
        await msg.add_reaction(Config().CMDSUCCESS)

    async def cmd_ladder(self, msg, *args):
        if len(args) != 1:
            await msg.add_reaction(Config().CMDERROR)
            return

        embed = discord.Embed()
        entries = {}
        for uid in Config().get(self)["ladder"]:
            member = discord.utils.get(msg.guild.members, id=uid)
            points = Config().get(self)["ladder"][uid]
            if points not in entries:
                entries[points] = [member]
            else:
                entries[points].append(member)

        values = []
        keys = sorted(entries.keys(), reverse=True)
        place = 0
        for el in keys:
            place += 1
            values.append("**#{}:** {} - {}".format(place, el, entries[el]))

        if len(values) == 0:
            await msg.channel.send("So far, nobody is on the ladder.")
            return

        embed.add_field(name="Ladder:", value="\n".join(values))
        await msg.channel.send(embed=embed)

    async def cmd_question(self, msg, *args):
        if len(args) != 1:
            await msg.add_reaction(Config().CMDERROR)
            return

        controller = self.get_controller(msg.channel)
        if controller is None:
            await msg.add_reaction(Config().CMDERROR)
            return

        embed = controller.quizapi.current_question().embed(emoji=True, info=True)
        await msg.channel.send(embed=embed)

    def update_ladder(self, member, points):
        ladder = Config().get(self)["ladder"]
        if len(ladder) > 0:
            print("ladder ids are str: {} (expected False)".format(isinstance(str, ladder[ladder.values()[0]])))
        if member.id in ladder:
            ladder[member.id] = int(round(ladder[member.id] * 3/4 + points * 1/4))
        else:
            ladder[member.id] = int(round(points * 3/4))
        Config().save(self)

    @commands.command(name="kwiss", help="Interacts with the kwiss subsystem.")
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
            self.logger.debug("Calling subcommand: {}".format(subcmd.callback))
            await subcmd.callback(ctx.message, *subcmd.args)
            return

        err = self.args_combination_check(controller_class, args)
        if err is not None:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config().lang(self, err))
            return

        # Look for existing quiz
        method = args["method"]
        modifying = method == Methods.STOP \
            or method == Methods.PAUSE \
            or method == Methods.RESUME \
            or method == Methods.SCORE \
            or method == Methods.STATUS
        if method == Methods.START and self.get_controller(channel):
            await ctx.add_reaction(Config().CMDERROR)
            raise QuizInitError(self, "existing_quiz")
        if modifying and self.get_controller(channel) is None:
            if method == Methods.STATUS:
                await ctx.send(Config().lang(self, "status_no_quiz"))
            return

        # Not starting a new quiz
        if modifying:
            quiz_controller = self.get_controller(channel)
            if method == Methods.PAUSE:
                await quiz_controller.pause(ctx.message)
            elif method == Methods.RESUME:
                await quiz_controller.resume(ctx.message)
            elif method == Methods.SCORE:
                await ctx.send(embed=quiz_controller.score.embed())
            elif method == Methods.STOP:
                if permChecks.check_full_access(ctx.message.author) or quiz_controller.requester == ctx.message.author:
                    await self.abort_quiz(channel, ctx.message)
            elif method == Methods.STATUS:
                await quiz_controller.status(ctx.message)
            else:
                assert False
            return

        # Starting a new quiz
        assert method == Methods.START
        await ctx.message.add_reaction(Config().EMOJI["success"])
        quiz_controller = controller_class(self, self.config, OpenTDBQuizAPI, ctx.channel, ctx.message.author,
                                           category=args["category"], question_count=args["questions"],
                                           difficulty=args["difficulty"], debug=args["debug"])
        self.controllers[channel] = quiz_controller
        self.logger.debug("Registered quiz controller {} in channel {}".format(quiz_controller, ctx.channel))
        await ctx.send(Config().lang(self, "quiz_start", args["questions"],
                                     quiz_controller.quizapi.category_name(args["category"]),
                                     Difficulty.human_readable(quiz_controller.difficulty),
                                     self.controller_mapping[controller_class][0]))
        await quiz_controller.start(ctx.message)

    def register_subcommand(self, channel, subcommand, callback):
        """
        Registers a subcommand. If the subcommand is found in a command, the callback coroutine is called.
        :param channel: Channel in which the registering quiz takes place. None for global.
        :param subcommand: subcommand string that is looked for in incoming commands. Case-insensitive.
        :param callback: Coroutine of the type f(msg, *args); is called with the message object and every arg, including
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

    def args_combination_check(self, controller, args):
        return None
        # Ranked stuff
        if args["ranked"]:
            pass

    def parse_args(self, channel, args):
        """
        Parses the arguments given to the quiz command and fills in defaults if necessary.
        :param channel: Channel in which the command was issued
        :param args: argument list
        :return: Dict with the parsed arguments
        """
        found = {el: False for el in self.defaults}
        parsed = self.defaults.copy()
        controller = self.default_controller
        controller_found = False

        # Fish for subcommand
        subcmd = None
        for el in self.registered_subcommands:
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
            for db in quizapis:
                if arg == db:
                    if found["impl"]:
                        raise QuizInitError(self, "duplicate_db_arg")
                    parsed["impl"] = quizapis[db]
                    found["impl"] = True
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

            # category: opentdb
            cat = OpenTDBQuizAPI.category_key(arg)
            if cat is not None:
                if found["category"]:
                    raise QuizInitError(self, "dupiclate_cat_arg")
                parsed["category"] = cat
                found["category"] = True
                continue

            # debug
            if arg == "debug":
                parsed["debug"] = True
                found["debug"] = True
                continue

            raise QuizInitError(self, "unknown_arg", arg)

        self.logger.debug("Parsed kwiss args: {}".format(parsed))
        return controller, parsed
