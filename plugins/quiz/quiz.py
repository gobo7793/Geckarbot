import logging
import warnings
from enum import Enum

import discord
from discord.ext import commands
from discord.errors import HTTPException

from base.configurable import BasePlugin
from data import Storage, Lang, Config
from botutils import permchecks
from botutils.stringutils import paginate
from botutils.utils import sort_commands_helper, add_reaction, helpstring_helper
from botutils.setter import ConfigSetter
from services.helpsys import DefaultCategories

from plugins.quiz.controllers import RushQuizController, PointsQuizController
from plugins.quiz.quizapis import quizapis, MetaQuizAPI
from plugins.quiz.base import Difficulty, Rankedness
from plugins.quiz.utils import get_best_username
from plugins.quiz.migrations import migration
from plugins.quiz.categories import CategoryController, DefaultCategory


class QuizInitError(Exception):
    def __init__(self, plugin, msg_id, *args):
        super().__init__(Lang.lang(plugin, msg_id, *args))


class SubCommandEncountered(Exception):
    """
    Flow control for argument parsing
    """
    def __init__(self, callback, args):
        super().__init__()
        self.callback = callback
        self.args = args


class Methods(Enum):
    """
    Commands for a (running) quiz
    """
    START = "start"
    STOP = "stop"
    SCORE = "score"
    PAUSE = "pause"
    RESUME = "resume"
    STATUS = "status"


class Plugin(BasePlugin, name="A trivia kwiss"):
    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category=DefaultCategories.GAMES)
        self.logger = logging.getLogger(__name__)
        self.controllers = {}
        self.registered_subcommands = {}
        self.category_controller = CategoryController()

        self.base_config = {
            "ranked_min_players": [int, 4],
            "ranked_min_questions": [int, 7],
            "ranked_auto": [bool, True],
            "questions_limit": [int, 25],
            "questions_default": [int, 10],
            "points_quiz_register_timeout": [int, 60],
            "points_quiz_question_timeout": [int, 20],  # warning after this value, actual timeout after 1.5*this value
            "question_cooldown": [int, 5],
            "emoji_in_pose": [bool, True],
            "catlist_embeds": [bool, False]
        }
        self.config_setter = ConfigSetter(self, self.base_config)
        self.role = self.bot.guild.get_role(Config().get(self).get("roleid", 0))

        # init quizapis
        for _, el in quizapis.items():
            el.register_categories(self.category_controller)
        MetaQuizAPI.register_categories(self.category_controller)

        self.default_controller = PointsQuizController
        self.defaults = {
            "quizapi": MetaQuizAPI,
            "questions": self.get_config("questions_default"),
            "method": Methods.START,
            "category": DefaultCategory.ALL,
            "difficulty": Difficulty.EASY,
            "ranked": False,
            "unranked": False,
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

        # Migrate data if necessary
        migration(self, self.logger)

        @commands.Cog.listener()
        async def on_message(msg):
            quiz = self.get_controller(msg.channel)
            if quiz:
                await quiz.on_message(msg)

    def get_config(self, key):
        return Config.get(self).get(key, self.base_config[key][1])

    def default_config(self, container=None):
        return {
            "roleid": 0,
        }

    def default_storage(self, container=None):
        return {
            "emoji": {},
            "ladder": {},
        }

    #####
    # Help
    #####
    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def sort_commands(self, ctx, command, subcommands):
        # category help
        if command is None:
            return subcommands

        # Subcommands for kwiss
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
        return sort_commands_helper(subcommands, order)

    #####
    # Commands
    #####
    @commands.group(name="kwiss", invoke_without_command=True)
    async def cmd_kwiss(self, ctx, *args):
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
            self.logger.debug("Calling subcommand: %s, %s", subcmd.callback, subcmd.args)
            await subcmd.callback(ctx, *subcmd.args)
            return

        err = self.args_combination_check(controller_class, args)
        if err is not None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, *err))
            return

        # Look for existing quiz
        method = args["method"]
        if method == Methods.START and self.get_controller(channel):
            await add_reaction(ctx.message, Lang.CMDERROR)
            raise QuizInitError(self, "existing_quiz")

        # Start a new quiz
        assert method == Methods.START
        await add_reaction(ctx.message, Lang.EMOJI["success"])
        cat = self.category_controller.get_category_key(args["quizapi"], args["category"])
        rankedness = self.rankedness(controller_class, args)
        self.logger.debug("Starting kwiss: controller %s, api %s,  channel %s, author %s, cat %s, question "
                          "count %s, difficulty %s, debug %s, ranked %s, gecki %s", controller_class,
                          args["quizapi"], ctx.channel, ctx.message.author, cat, args["questions"], args["difficulty"],
                          args["debug"], args["ranked"], args["gecki"])
        async with ctx.typing():
            quiz_controller = controller_class(self,
                                               args["quizapi"],
                                               ctx.channel,
                                               ctx.message.author,
                                               category=cat,
                                               question_count=args["questions"],
                                               difficulty=args["difficulty"],
                                               debug=args["debug"],
                                               ranked=rankedness,
                                               gecki=args["gecki"])
            self.controllers[channel] = quiz_controller
            self.logger.debug("Registered quiz controller %s in channel %s", quiz_controller, ctx.channel)
            await quiz_controller.status(ctx.message)
            await quiz_controller.start(ctx.message)

    @commands.has_role(Config().BOT_ADMIN_ROLE_ID)
    @cmd_kwiss.command(name="set", aliases=["config"], hidden=True)
    async def cmd_set(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        await self.config_setter.set_cmd(ctx, key, value)

    @cmd_kwiss.command(name="status")
    async def cmd_status(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "status_no_quiz"))
        else:
            await controller.status(ctx.message)

    @cmd_kwiss.command(name="score")
    async def cmd_score(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
        else:
            await ctx.send(embed=controller.score.embed())

    @cmd_kwiss.command(name="stop")
    async def cmd_stop(self, ctx):
        controller = self.get_controller(ctx.channel)
        if controller is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
        elif permchecks.check_mod_access(ctx.message.author) or controller.requester == ctx.message.author:
            await self.abort_quiz(ctx.channel)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)

    @cmd_kwiss.command(name="emoji")
    async def cmd_emoji(self, ctx, *args):
        # Delete emoji
        if len(args) == 0:
            if ctx.message.author.id in Storage().get(self)["emoji"]:
                del Storage().get(self)["emoji"][ctx.message.author.id]
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
                Storage().save(self)
            else:
                await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        # Too many arguments
        if len(args) != 1:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        emoji = args[0]
        try:
            await add_reaction(ctx.message, emoji)
        except HTTPException:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        Storage().get(self)["emoji"][ctx.message.author.id] = emoji
        Storage().save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_kwiss.command(name="ladder")
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

    @cmd_kwiss.command(name="del", usage="<user>")
    async def cmd_del(self, ctx, *args):
        if len(args) != 1:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        if not permchecks.check_mod_access(ctx.message.author):
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        try:
            user = await commands.MemberConverter().convert(ctx, args[0])
        except (commands.CommandError, IndexError):
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        ladder = Storage().get(self)["ladder"]
        if user.id in ladder:
            del ladder[user.id]
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    @cmd_kwiss.command(name="categories")
    async def cmd_categories(self, ctx):
        # Embed format
        if self.get_config("catlist_embeds"):
            entries = discord.Embed()
            for cat in self.category_controller.categories.values():
                entries.add_field(name=cat.name, value=cat.args[0])
            await ctx.send(embed=entries)
            return

        # Table format
        longest_cat = len("Category")
        longest_arg = len("Argument")
        entries = [("Category", "Argument")]
        for cat in self.category_controller.categories.values():
            arg = cat.args[0]
            if len(cat.name) > longest_cat:
                longest_cat = len(cat.name)
            if len(arg) > longest_arg:
                longest_arg = len(arg)
            entries.append((cat.name, arg))

        for i in range(len(entries)):
            name = entries[i][0]
            name = name + " " * (1 + longest_cat - len(name))
            entries[i] = name + "| " + entries[i][1]

        underline = "-" * (1 + longest_cat) + "+" + "-" * longest_cat
        entries = entries[:1] + [underline] + entries[1:]

        for msg in paginate(entries, prefix="```", suffix="```"):
            await ctx.send(msg)

    @cmd_kwiss.command(name="question")
    async def cmd_question(self, ctx, *args):
        if len(args) != 0:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("Too many arguments")
            return

        controller = self.get_controller(ctx.channel)
        if controller is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("No kwiss running")
            return

        embed = controller.quizapi.current_question().embed(emoji=True, info=True)
        await ctx.channel.send(embed=embed)

    @cmd_kwiss.command(name="role")
    async def cmd_role(self, ctx, role: discord.Role):
        if not permchecks.check_mod_access(ctx.author) and not permchecks.check_admin_access(ctx.author) \
                and not permchecks.is_botadmin(ctx.author):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self, "permissions"))
            return

        Config.get(self)["roleid"] = role.id
        self.role = role
        Config.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_kwiss.command(name="info", hidden=True)
    async def cmd_info(self, ctx, *args):
        args = args[1:]
        _, args = self.parse_args(ctx.channel, args, subcommands=False)
        infodict = await args["quizapi"].info(**args)
        embed = discord.Embed()
        for key in infodict:
            embed.add_field(name=key, value=infodict[key])

        await ctx.send(args["quizapi"].info(**args))

    #####
    # Interface
    #####
    def update_ladder(self, member, points):
        """
        Updates the ranked ladder.

        :param member: Discord member
        :param points: Points of the quiz round that triggered this update
        """
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
        :param callback: Coroutine of the type `f(ctx, *args)`; is called with the context object and every arg,
            including the subcommand itself and excluding the main command ("kwiss")
        """
        self.logger.debug("Subcommand registered: %s; callback: %s", subcommand, callback)
        subcommand = subcommand.lower()
        found = False
        for el in self.registered_subcommands:
            if el == channel:
                found = True
                if subcommand in self.registered_subcommands[channel]:
                    warnings.warn(RuntimeWarning("Subcommand was registered twice: %s", subcommand))
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

    async def abort_quiz(self, channel):
        """
        Called on !kwiss stop. It is assumed that there is a quiz in channel.

        :param channel: channel that the abort was requested in.
        """
        controller = self.controllers[channel]
        controller.cancel()
        controller.cleanup()
        del self.controllers[channel]

    def end_quiz(self, channel):
        """
        Cleans up the quiz.

        :param channel: channel that the quiz is taking place in
        """
        self.logger.debug("Cleaning up quiz in channel %s.", channel)
        if channel not in self.controllers:
            assert False, "Channel not in controller list"
        del self.controllers[channel]

    #####
    # Parse arguments
    #####
    def args_combination_check(self, controller, args):
        """
        Checks for argument combination constraints.

        :param controller: Quiz controller class
        :param args: args dict
        :return: (lang code, args...) for error msg, None if the arg combination is okay
        """
        # Ranked constraints
        if args["ranked"] and not args["debug"]:
            if controller != self.default_controller:
                self.logger.debug("Ranked constraints violated: controller %s != %s",
                                  controller, self.default_controller)
                return ["ranked_constraints"]
            #if args["category"] != self.defaults["category"]:
            #    self.logger.debug("Ranked constraints violated: cat {} != {}"
            #                      .format(args["category"], self.defaults["category"]))
            #    return "ranked_constraints"
            if args["difficulty"] != self.defaults["difficulty"]:
                self.logger.debug("Ranked constraints violated: difficulty %s != %s",
                                  args["difficulty"], self.defaults["difficulty"])
                return ["ranked_constraints"]
            if args["questions"] < self.get_config("ranked_min_questions"):
                return "ranked_questioncount", self.get_config("ranked_min_questions")
            if not self.bot.DEBUG_MODE and args["gecki"]:
                return ["ranked_gecki"]

        # Category support
        if args["quizapi"] not in self.category_controller.get_supporters(args["category"]):
            return "category_not_supported", args["quizapi"].NAME, args["category_name"]
        return None

    def rankedness(self, controller, args) -> Rankedness:
        """
        Decides whether a quiz is supposed to be ranked, auto (can potentially be ranked, going to depend on player
        count) or unranked.

        :param controller: Controller class, corresponds to game mode
        :param args: Parsed args
        :return: Resulting Rankedness object
        """
        if args["ranked"]:
            return Rankedness.RANKED
        if args["unranked"] or not self.get_config("ranked_auto"):
            return Rankedness.UNRANKED

        # ranked constraints
        if controller != self.default_controller:
            return Rankedness.UNRANKED

        return Rankedness.AUTO

    def parse_args(self, channel, args, subcommands=True):
        """
        Parses the arguments given to the quiz command and fills in defaults if necessary.

        :param channel: Channel in which the command was issued
        :param args: argument list
        :param subcommands: Whether to fish for subcommands
        :return: Dict with the parsed arguments
        :raises QuizInitError: Raised if arguments violate conditions (aka make no sense)
        :raises SubCommandEncountered: Flow controll for registered subcommands
        """
        self.logger.debug("Parsing args: %s", args)
        found = {el: False for el in self.defaults}
        parsed = self.defaults.copy()
        controller = self.default_controller
        controller_found = False

        # Fish for subcommand
        subcmd = None
        for key, el in self.registered_subcommands.items():
            if not subcommands:
                break
            if key is not None and key != channel:
                continue
            for arg in args:
                if arg in el:
                    if subcmd is not None:
                        raise QuizInitError(self, "duplicate_subcmd_arg")
                    subcmd = el[arg]
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
                if arg > self.get_config("questions_limit"):
                    raise QuizInitError(self, "too_many_questions", arg)
                parsed["questions"] = arg
                found["questions"] = True
                continue
            except (ValueError, TypeError):
                pass

            # Quiz database
            quizapi_found = False
            for db_arg, apiclass in quizapis.items():
                if arg == db_arg:
                    if found["quizapi"]:
                        raise QuizInitError(self, "duplicate_db_arg")
                    parsed["quizapi"] = apiclass
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
            for key, key in self.controller_mapping.items():
                if arg in key:
                    if controller_found:
                        raise QuizInitError(self, "duplicate_controller_arg")
                    controller = key
                    controller_found = True
                    break
            if controller_found:
                continue

            # ranked
            if arg == "ranked":
                if found["unranked"]:
                    raise QuizInitError(self, "duplicate_ranked_arg")
                parsed["ranked"] = True
                found["ranked"] = True
                continue

            if arg == "unranked":
                if found["ranked"]:
                    raise QuizInitError(self, "duplicate_ranked_arg")
                parsed["unranked"] = True
                found["unranked"] = True
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
            cat = self.category_controller.get_cat_by_arg(arg)
            if cat is not None:
                if found["category"]:
                    raise QuizInitError(self, "duplicate_cat_arg")
                parsed["category_name"] = arg
                parsed["category"] = cat
                found["category"] = True
                continue

            raise QuizInitError(self, "unknown_arg", arg)

        self.logger.debug("Parsed kwiss args: %s", parsed)
        return controller, parsed
