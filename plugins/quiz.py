import string
import random
import logging
import warnings
from abc import ABC, abstractmethod
from enum import Enum
from threading import Lock, Timer
from urllib.parse import unquote

import discord
from discord.ext import commands

from botutils import restclient, utils, permChecks


"""
FEATURE IDEAS
# configurable user icons
# submit questions
# ranked
# repeat question
# pings
# config api
"""


jsonify = {
    "timeout": 20,  # answering timeout in minutes; not impl yet TODO
    "timeout_warning": 2,  # warning time before timeout in minutes
    "questions_limit": 50,
    "questions_default": 20,
    "default_category": -1,
    "channel_blacklist": [],
    "points_quiz_register_timeout": 1 * 60,
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

msg_defaults = {
    "too_many_questions": "Sorry, too many questions. Limit is {}",
    "duplicate_count_arg": "You defined how many questions you want more than once. Make up your mind.",
    "duplicate_db_arg": "You defined which database you want more than once. Make up your mind.",
    "duplicate_method_arg": "You defined what you want me to do more than once. Make up your mind.",
    "duplicate_cat_arg": "Sorry, specifying more than one argument is not supported.",
    "duplicate_difficulty_arg": "You defined the difficulty more than once. Make up your mind.",
    "duplicate_mode_arg": "You defined the answering mode more than once. Make up your mind.",
    "unknown": "Unknown argument: {}",
    "existing_quiz": "There is already a quiz running in this channel.",
    "correct_answer": "{}: {} is the correct answer!",
    "multiplechoice": "Multiple Choice",
    "freetext": "Free text",
    "quiz_start": "Starting Quiz! {} questions. Category: {}. Difficulty: {}. Mode: {}",
    "quiz_end": "The quiz has ended. The winner is: **{}**! Congratulations!",
    "quiz_abort": "The quiz was aborted.",
    "too_many_arguments": "Too many arguments.",
    "invalid_argument": "Invalid argument: {}",
    "registering_phase": "Please register for the upcoming quiz via !kwiss register. I will wait {} minutes.",
    "registering_too_late": "{}: Sorry, too late. The quiz has already begun.",
    "already_registered": "{}: Dude, I got it. Don't worry.",
    "no_pause_while_registering": "{}: Nope, not now.",
}

opentdb = {
    "base_url": "https://opentdb.com",
    "token_route": "api_token.php",
    "api_route": "api.php",
    "cat_mapping": [
        {'id': -1, 'names': ['Any', 'any', 'none', 'all', 'null']},
        {'id': 9,  'names': ['General', 'general']},
        {'id': 10, 'names': ['Books', 'books']},
        {'id': 11, 'names': ['Film', 'film']},
        {'id': 12, 'names': ['Music', 'music']},
        {'id': 13, 'names': ['Musical / Theatre', 'musical', 'musicals', 'theatres', 'theatre', 'theater', 'theaters']},
        {'id': 14, 'names': ['T.V.', 'television', 'tv']},
        {'id': 15, 'names': ['Games', 'games']},
        {'id': 16, 'names': ['Boardgames', 'boardgames']},
        {'id': 17, 'names': ['Science / Nature', 'science', 'nature']},
        {'id': 18, 'names': ['Computers', 'computers', 'computer', 'it']},
        {'id': 19, 'names': ['Mathematics', 'mathematics', 'math']},
        {'id': 20, 'names': ['Mythology', 'mythology']},
        {'id': 21, 'names': ['Sports', 'sport', 'sports']},
        {'id': 22, 'names': ['Geography', 'geography', 'geo']},
        {'id': 23, 'names': ['History', 'history']},
        {'id': 24, 'names': ['Politics', 'politics']},
        {'id': 25, 'names': ['Art', 'art']},
        {'id': 26, 'names': ['Celebrities', 'celebrities']},
        {'id': 27, 'names': ['Animals', 'animals']},
        {'id': 28, 'names': ['Vehicles', 'vehicles']},
        {'id': 29, 'names': ['Comics', 'comics']},
        {'id': 30, 'names': ['Gadgets', 'gadgets']},
        {'id': 31, 'names': ['Anime / Manga', 'anime', 'manga']},
        {'id': 32, 'names': ['Cartoons / Animated', 'cartoon', 'cartoons']},
    ]
}


def message(config, msg_id, *args):
    """
    Builds a message out of configured messages and defaults.
    :param config: Config dict
    :param msg_id: Message key out of msg_defaults
    :param args: Format string args
    :return: Compiled message
    """
    msg = msg_id
    if msg_id in config:
        msg = config[msg_id].format(*args)
    elif msg_id in msg_defaults:
        msg = msg_defaults[msg_id].format(*args)
    return msg


class QuizInitError(Exception):
    def __init__(self, config, msg_id, *args):
        super().__init__(message(config, msg_id, *args))


class QuizEnded(Exception):
    """
    To be raised by the Quiz class on get_question() if the quiz has ended (for whatever reason)
    """
    pass


class QuizNotRunning(Exception):
    pass


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @staticmethod
    def human_readable(el):
        if el == Difficulty.EASY:
            return "Easy"
        if el == Difficulty.MEDIUM:
            return "Medium"
        if el == Difficulty.HARD:
            return "Hard"


class Methods(Enum):
    START = "start"
    STOP = "stop"
    SCORE = "score"
    PAUSE = "pause"
    RESUME = "resume"
    STATUS = "status"


class Modes(Enum):
    MULTIPLECHOICE = "multiplechoice",
    FREETEXT = "freetext"

    @staticmethod
    def human_readable(el):
        if el == Modes.MULTIPLECHOICE:
            return "Multiple choice"
        if el == Modes.FREETEXT:
            return "Free text"


class BaseQuizAPI(ABC):
    @abstractmethod
    def current_question(self):
        """
        Retrieves the current question.
        :return: Question object
        """
        pass

    @abstractmethod
    def next_question(self):
        """
        Retrieves a new question.
        :return: Question object
        """
        pass

    @abstractmethod
    def __del__(self):
        """
        Called when the quiz is stopped.
        """
        pass


class BaseQuizController(ABC):
    @abstractmethod
    def __init__(self, plugin, config, quizapi, channel, requester, **kwargs):
        pass

    @abstractmethod
    async def start(self):
        """
        Called when the start command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def pause(self):
        """
        Called when the pause command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def resume(self):
        """
        Called when the resume command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def status(self):
        """
        Called when the status command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    def score(self):
        """
        :return: Score object
        """
        raise NotImplementedError

    @abstractmethod
    async def on_message(self, msg):
        raise NotImplementedError

    @abstractmethod
    def __del__(self):
        """
        Called when the quiz is stopped.
        """
        pass


class Score:
    def __init__(self):
        self._score = {}

    def calc_points(self, user):
        """
        :param user: The user whose points are to be calculated
        :return: user's points
        """
        if user not in self._score:
            raise KeyError("User {} not found in score".format(user))

        total = 0
        for el in self._score:
            total += self._score[el]
        return int(100 * (self._score[user] / total / len(self._score)))

    def points(self):
        """
        :return: A dict that contains the points of all participants.
        """
        r = {}
        for el in self._score:
            r[el] = self.calc_points(el)
        return r

    @property
    def score(self):
        return self._score.copy()

    def ladder(self):
        """
        :return: List of members in score, sorted by score
        """
        return sorted(self._score, key=lambda x: self._score[x])

    def embed(self):
        embed = discord.Embed(title="Score:")

        ladder = self.ladder()
        place = 0
        for i in range(len(ladder)):
            user = ladder[i]
            if i == 0 or self._score[user] > self._score[ladder[i - 1]]:
                place += 1

            # embed
            name = "**#{}** {}".format(place, utils.get_best_username(user))
            value = "Correct questions: {}\nScore: {}".format(self._score[user], self.calc_points(user))
            embed.add_field(name=name, value=value)

            i += 1

        if len(ladder) == 0:
            embed.add_field(name="Nobody has scored yet!", value="")

        return embed

    def increase(self, member, amount=1):
        if member in self._score:
            self._score[member] += amount
        else:
            self._score[member] = amount


class InvalidAnswer(Exception):
    pass


class Question:
    def __init__(self, question, correct_answer, incorrect_answers, mode=Modes.MULTIPLECHOICE):
        logging.debug("Question({}, {}, {}, mode={})".format(question, correct_answer, incorrect_answers, mode))
        self.mode = mode
        self.question = question
        self.correct_answer = correct_answer
        self.incorrect_answers = incorrect_answers
        self.all_answers = incorrect_answers.copy()
        self.all_answers.append(correct_answer)
        self.last_author = None
        random.shuffle(self.all_answers)

    async def pose(self, channel):
        await channel.send(embed=self.embed())

    def embed(self):
        """
        :return: An embed representation of the question.
        """
        embed = discord.Embed(title=self.question)
        if self.mode == Modes.MULTIPLECHOICE:
            value = "\n".join([el for el in self.answers_mc()])
            embed.add_field(name="Antwortmöglichkeiten:", value=value)

        elif self.mode != Modes.FREETEXT:
            assert False

        return embed

    def answers_mc(self):
        """
        :return: Generator for possible answers in a multiple-choice-fashion, e.g. "A: Jupiter"
        """
        for i in range(len(self.all_answers)):
            letter = string.ascii_uppercase[i]
            yield "**{}:** {}".format(letter, self.all_answers[i])

    def check_answer(self, author, answer):
        """
        Called to check the answer to the most recent question that was retrieved via qet_question().
        :return: True if this is the first occurence of the correct answer, False otherwise
        """
        if author == self.last_author:  # TODO move to controller
            return False

        answer = answer.strip()
        if self.mode == Modes.MULTIPLECHOICE:
            answer = answer.lower()
            found = False
            for i in range(len(string.ascii_lowercase)):
                letter = string.ascii_lowercase[i]
                if answer == letter:
                    found = True
                    if self.all_answers[i] == self.correct_answer:
                        return True
                    else:
                        break

            # answer is not a letter and therefore invalid
            if not found:
                raise InvalidAnswer()

        elif self.mode == Modes.FREETEXT:
            if answer.lower() == self.correct_answer.lower():
                # TODO improve recognition, e.g. remove whitespace, dots, determiners etc
                return True
            return False

        assert False


class Phases(Enum):
    BEFORE: 0
    REGISTERING: 1
    QUIZ: 2


class PointsQuizController(BaseQuizController):
    """
    Gamemode: every user with the correct answer gets a point
    """
    # TODO support DMs
    def __init__(self, plugin, config, quizapi, channel, requester, **kwargs):
        """
        :param plugin: Plugin object
        :param config: config
        :param quizapi: BaseQuizAPI object
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, config, quizapi, channel, requester, **kwargs)
        logging.debug("Building PointsQuizController; kwargs: {}".format(kwargs))
        self.cmdstring_register = "register"

        self.channel = channel
        self.requester = requester
        self.config = config
        self.plugin = plugin

        self.category = kwargs["category"]
        self.debug = kwargs["debug"]
        self.difficulty = kwargs["difficulty"]
        self.question_count = kwargs["question_count"]
        self.quizapi = quizapi(config, channel, category=self.category, question_count=self.question_count,
                               difficulty=self.difficulty, debug=self.debug)

        self.phase = Phases.BEFORE
        self.has_ever_run = False
        self.is_running = False
        self.questions = []
        self._score = Score()

        self.registered_participants = []
        self.registering_lock = Lock()

        self.answering_lock = Lock()
        self.current_answers = {}

    async def status(self):
        embed = discord.Embed(title="Quiz: question {}/{}".format(
            self.quizapi.current_question_i() + 1, len(self.questions)))
        embed.add_field(name="Category", value=self.quizapi.category_name())
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Winner takes it all")
        embed.add_field(name="Initiated by", value=utils.get_best_username(self.requester))

        status = ":arrow_forward: Running"
        if not self.is_running:
            status = ":pause_button: Paused"
        embed.add_field(name="Status", value=status)

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        await self.channel.send(embed=embed)
        if self.is_running:
            self.quizapi.current_question().pose(self.channel)

    @property
    def score(self):
        return self._score

    async def start(self):
        logging.debug("Starting RaceQuizController")
        if self.is_running or self.has_ever_run:
            return
        self.is_running = True
        self.has_ever_run = True
        await self.quizapi.next_question().pose(self.channel)
        # TODO

    async def pause(self):
        self.is_running = False

    def resume(self):
        if self.is_running:
            return
        self.is_running = True
        self.status()

    def has_everyone_answered(self):
        if len(self.registered_participants) > len(self.current_answers):
            return False

        assert len(self.registered_participants) == len(self.current_answers)

        for el in self.registered_participants:
            if el not in self.current_answers:
                # a non-participant managed to get into the list
                assert False

        return True

    async def on_message(self, msg):
        # ignore DMs
        if not isinstance(msg.channel, discord.TextChannel):
            return

        if not self.is_running:
            return

        # Correct answer
        try:
            check = self.quizapi.current_question().check_answer(msg.author, msg.content)
        except InvalidAnswer:
            return

        if check:
            self.score.increase(msg.author)
            await msg.channel.send(message(self.config, "correct_answer",
                                           "@" + utils.get_best_username(msg.author),
                                           self.quizapi.current_question().correct_answer))
            try:
                await msg.channel.send(embed=self.quizapi.next_question().embed())
            except QuizEnded:
                endmsg, embed = self.plugin.end_quiz(msg.channel)
                await msg.channel.send(endmsg, embed=embed)

    async def register_command(self, msg, *args):
        """
        This is the callback for !kwiss register.
        :param msg: Message object
        :param args: Passed arguments, including "register"
        """
        assert self.cmdstring_register in args
        if len(args) > 1:
            await self.channel.send(message(self.config, "too_many_arguments"))
            return

        with self.registering_lock:
            if self.phase == Phases.BEFORE:
                await self.channel.send("No idea how you did that, but you registered too early.")
                return

            if self.phase == Phases.QUIZ:
                await self.channel.send(message(self.config, "registering_too_late", msg.author))

    def end_registering(self):
        with self.registering_lock:
            self.phase = Phases.QUIZ


    def __del__(self):
        pass


class RaceQuizController(BaseQuizController):
    """
    Gamemode: the first user with the correct answer gets the point for the round
    """
    def __init__(self, plugin, config, quizapi, channel, requester, **kwargs):
        """
        :param plugin: Plugin object
        :param config: config
        :param quizapi: BaseQuizAPI object
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, config, quizapi, channel, requester, **kwargs)
        logging.debug("Building RaceQuizController; kwargs: {}".format(kwargs))
        self.channel = channel
        self.requester = requester
        self.config = config
        self.plugin = plugin

        self.category = kwargs["category"]
        self.debug = kwargs["debug"]
        self.difficulty = kwargs["difficulty"]
        self.question_count = kwargs["question_count"]
        self.quizapi = quizapi(config, channel, category=self.category, question_count=self.question_count,
                               difficulty=self.difficulty, debug=self.debug)

        self.has_ever_run = False
        self.is_running = False
        self._score = Score()

        self.last_author = None

    async def status(self):
        embed = discord.Embed(title="Quiz: question {}/{}".format(
            self.quizapi.current_question_index() + 1, len(self.quizapi.questions)))
        embed.add_field(name="Category", value=self.quizapi.category_name())
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Winner takes it all")
        embed.add_field(name="Initiated by", value=utils.get_best_username(self.requester))

        status = ":arrow_forward: Running"
        if not self.is_running:
            status = ":pause_button: Paused"
        embed.add_field(name="Status", value=status)

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        await self.channel.send(embed=embed)
        if self.is_running:
            self.quizapi.current_question().pose(self.channel)

    @property
    def score(self):
        return self._score

    async def start(self):
        logging.debug("Starting RaceQuizController")
        if self.is_running or self.has_ever_run:
            return
        self.is_running = True
        self.has_ever_run = True
        await self.quizapi.next_question().pose(self.channel)

    async def pause(self):
        self.is_running = False
        await self.status()

    async def resume(self):
        if self.is_running:
            return
        self.is_running = True
        await self.status()

    async def on_message(self, msg):
        # ignore DMs
        if not isinstance(msg.channel, discord.TextChannel):
            return

        if not self.is_running:
            return

        # Correct answer
        try:
            check = self.quizapi.current_question().check_answer(msg.author, msg.content)
        except InvalidAnswer:
            return

        if check:
            self.score.increase(msg.author)
            await msg.channel.send(message(self.config, "correct_answer",
                                           "@" + utils.get_best_username(msg.author),
                                           self.quizapi.current_question().correct_answer))
            try:
                await msg.channel.send(embed=self.quizapi.next_question().embed())
            except QuizEnded:
                endmsg, embed = self.plugin.end_quiz(msg.channel)
                await msg.channel.send(endmsg, embed=embed)

    def __del__(self):
        pass


class OpenTDBQuizAPI(BaseQuizAPI):
    def __init__(self, config, channel,
                 category=None, question_count=None, mode=Modes.MULTIPLECHOICE, difficulty=Difficulty.EASY,
                 debug=False):
        """
        :param config: config dict
        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        logging.info("Quiz API: OpenTDB")
        self.config = config
        self.debug = debug
        self.channel = channel
        self.difficulty = difficulty
        self.mode = mode
        self.question_count = question_count
        if question_count is None:
            self.question_count = self.config["questions_default"]

        self.client = restclient.Client(opentdb["base_url"])
        self.current_question_i = -1

        self.category = None
        self.parse_category(category)
        self.questions = []

        # acquire API token
        self.token = self.client.make_request(opentdb["token_route"], params={"command": "request"})
        self.token = self.token["token"]

        # Acquire questions
        params = {
            "token": self.token,
            "amount": self.question_count,
            "encode": "url3986",
            "type": "multiple",
        }
        if self.category is not None and self.category > 0:
            params["category"] = self.category

        questions_raw = self.client.make_request(opentdb["api_route"], params=params)["results"]
        for el in questions_raw:
            question = unquote(el["question"])
            correct_answer = unquote(el["correct_answer"])
            incorrect_answers = [unquote(ia) for ia in el["incorrect_answers"]]
            self.questions.append(Question(question, correct_answer, incorrect_answers, mode=self.mode))

    def current_question_index(self):
        return self.current_question_i

    def parse_category(self, cat):
        """
        Takes all available info to determine the correct category.
        :param cat: Category that was given by User. None if none was given.
        """
        if cat is not None:
            self.category = cat

        elif self.channel.id in self.config["channel_mapping"]:
            self.category = self.config["channel_mapping"][self.channel.id]

        else:
            self.category = self.config["default_category"]

    def category_name(self):
        """
        :return: Human-readable representation of the quiz category
        """
        for el in opentdb["cat_mapping"]:
            if el["id"] == self.category:
                return el["names"][0]

        logging.error("Category not found: {}. This should not happen.".format(self.category))
        assert False

    def next_question(self):
        """
        Returns the next question and increments the current question. Raises QuizEnded when there is no next question.
        """
        self.current_question_i += 1
        if self.current_question_i > len(self.questions) - 1:
            raise QuizEnded

        return self.questions[self.current_question_i]

    def current_question(self):
        return self.questions[self.current_question_i]

    def __del__(self):
        self.is_running = False


db_mapping = {
    "opentdb": OpenTDBQuizAPI,
}


class Plugin(commands.Cog, name="A trivia quiz"):
    def __init__(self, bot):
        self.bot = bot
        self.controllers = {}
        self.registered_subcommands = {}
        self.config = jsonify

        self.default_controller = RaceQuizController
        self.defaults = {
            "impl": "opentdb",
            "questions": self.config["questions_default"],
            "method": Methods.START,
            "category": None,
            "difficulty": Difficulty.EASY,
            "mode": Modes.MULTIPLECHOICE,
            "debug": False,
            "subcommand": None,
        }

        self.controller_mapping = {
            RaceQuizController: ["race", "wtia"]
        }

        super(commands.Cog).__init__()
        bot.register(self)

        @bot.event
        async def on_message(msg):
            await bot.process_commands(msg)
            quiz = self.get_controller(msg.channel)
            if quiz:
                await quiz.on_message(msg)

    @commands.command(name="kwiss", help="Interacts with the kwis subsystem.")
    async def kwiss(self, ctx, *args):
        logging.debug("Caught kwiss cmd")
        channel = ctx.channel
        try:
            controller, args = self.parse_args(channel, args)
        except QuizInitError as e:
            # Parse Error
            await ctx.send(str(e))
            return

        # Subcommand
        if args["subcommand"] is not None:
            callback, args = args["subcommand"]
            callback(ctx.message, args)
            return

        # Look for existing quiz
        method = args["method"]
        modifying = method == Methods.STOP \
            or method == Methods.PAUSE \
            or method == Methods.RESUME \
            or method == Methods.SCORE \
            or method == Methods.STATUS
        if method == Methods.START and self.get_controller(channel):
            raise QuizInitError(self.config, "existing_quiz")
        if modifying and self.get_controller(channel) is None:
            return

        # Not starting a new quiz
        if modifying:
            quiz_controller = self.get_controller(channel)
            if method == Methods.PAUSE:
                await quiz_controller.pause()
            elif method == Methods.RESUME:
                await quiz_controller.resume()
            elif method == Methods.SCORE:
                await ctx.send(embed=quiz_controller.score.embed())
            elif method == Methods.STOP:
                if permChecks.check_full_access(ctx.message.author) or quiz_controller.requester == ctx.message.author:
                    msg, embed = self.end_quiz(channel)
                    await ctx.send(msg, embed=embed)
            elif method == Methods.STATUS:
                await quiz_controller.status()
            else:
                assert False
            return

        # Starting a new quiz
        assert method == Methods.START
        quiz_controller = controller(self, self.config, OpenTDBQuizAPI, ctx.channel, ctx.message.author,
                                     category=args["category"], question_count=args["questions"],
                                     difficulty=args["difficulty"], mode=args["mode"], debug=args["debug"])
        self.controllers[channel] = quiz_controller
        await ctx.send(message(self.config, "quiz_start", args["questions"], quiz_controller.quizapi.category_name(),
                       Difficulty.human_readable(quiz_controller.difficulty), Modes.human_readable(args["mode"])))
        await quiz_controller.start()

    def register_subcommand(self, channel, subcommand, callback):
        """
        Registers a subcommand. If the subcommand is found in a command, the callback function is called.
        :param channel: Channel in which the registering quiz takes place
        :param subcommand: subcommand string that is looked for in incoming commands. Case-insensitive.
        :param callback: Function of the type f(msg, *args); is called with the message object and every arg, including
        the subcommand itself and excluding the main command ("kwiss")
        """
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

    def end_quiz(self, channel):
        """
        Ends the quiz.
        :param channel: channel that the quiz is taking place in
        :return: (End message, score embed)
        """
        if channel not in self.controllers:
            assert False

        controller = self.controllers[channel]
        embed = controller.score.embed()
        winner = None
        ladder = controller.score.ladder()
        if ladder:
            winner = ladder[0]

        del self.controllers[channel]
        if winner is None:
            return message(self.config, "quiz_abort"), None
        return message(self.config, "quiz_end", winner), embed

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

        for arg in args:
            arg = arg.lower()

            # Question count
            try:
                arg = int(arg)
                if found["questions"]:
                    raise QuizInitError(self.config, "duplicate_count_arg")
                if arg > self.config["questions_limit"]:
                    raise QuizInitError(self.config, "too_many_questions", arg)
                parsed["questions"] = arg
                found["questions"] = True
                continue
            except (ValueError, TypeError):
                pass

            # Quiz database
            for db in db_mapping:
                if arg == db:
                    if found["impl"]:
                        raise QuizInitError(self.config, "duplicate_db_arg")
                    parsed["impl"] = db_mapping[db]
                    found["impl"] = True
                    continue

            # method
            try:
                method = Methods(arg)
                if found["method"]:
                    raise QuizInitError(self.config, "duplicate_method_arg")
                parsed["method"] = method
                found["method"] = True
                continue
            except ValueError:
                pass

            # difficulty
            try:
                difficulty = Difficulty(arg)
                if found["difficulty"]:
                    raise QuizInitError(self.config, "duplicate_difficulty_arg")
                parsed["difficulty"] = difficulty
                found["difficulty"] = True
                continue
            except ValueError:
                pass

            # mode
            try:
                mode = Modes(arg)
                if mode == Modes.FREETEXT:
                    raise QuizInitError(self.config, "Sorry, the free text mode isn't quite ready yet.")
                if found["mode"]:
                    raise QuizInitError(self.config, "duplicate_mode_arg")
                parsed["mode"] = mode
                found["mode"] = True
                continue
            except ValueError:
                pass

            # controller
            for el in self.controller_mapping:
                if arg in self.controller_mapping[el]:
                    if controller is not None:
                        raise QuizInitError(self.config, "duplicate_controller_arg")
                    controller = el
                    break

            # category: opentdb
            for mapping in opentdb["cat_mapping"]:
                for cat in mapping["names"]:
                    if arg.lower() == cat:
                        if found["category"]:
                            raise QuizInitError(self.config, "dupiclate_cat_arg")
                        parsed["category"] = mapping["id"]
                        found["category"] = True
            if found["category"]:
                continue

            # debug
            if arg == "debug":
                parsed["debug"] = True
                found["debug"] = True
                continue

            # registered subcommand
            if channel in self.registered_subcommands and arg in self.registered_subcommands[channel]:
                if found["subcommand"]:
                    raise QuizInitError(self.config, "duplicate_subcommand")
                found["subcommand"] = True
                parsed["subcommand"] = self.registered_subcommands[channel], args

            raise QuizInitError(self.config, "unknown_arg", arg)

        logging.debug("Parsed kwiss args: {}".format(parsed))
        return controller, parsed
