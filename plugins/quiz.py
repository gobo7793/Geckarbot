import string
import random
import logging
from abc import ABC, abstractmethod
from enum import Enum
from urllib.parse import unquote

import discord
from discord.ext import commands

from botUtils import restclient


jsonify = {
    "timeout": 20,  # answering timeout in minutes; not impl yet TODO
    "timeout_warning": 2,  # warning time before timeout in minutes
    "questions_limit": 50,
    "questions_default": 20,
    "default_category": -1,
    "channel_blacklist": [],
    "too_many_questions": "Zuviele Fragen. Das Limit ist {}.",
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
    "correct_answer": "{}: Right answer!",
    "multiplechoice": "Multiple Choice",
    "freetext": "Free text",
    "quiz_start": "Starting Quiz! {} questions. Category: {}. Difficulty: {}. Mode: {}"
}

opentdb = {
    "base_url": "https://opentdb.com",
    "token_route": "api_token.php",
    "api_route": "api.php",
    "cat_mapping": [
        {'id': -1, 'names': ['any', 'none', 'all', 'null']},
        {'id': 9,  'names': ['general']},
        {'id': 10, 'names': ['books']},
        {'id': 11, 'names': ['film']},
        {'id': 12, 'names': ['music']},
        {'id': 13, 'names': ['musical', 'musicals', 'theatres', 'theatre']},
        {'id': 14, 'names': ['television', 'tv']},
        {'id': 15, 'names': ['games']},
        {'id': 16, 'names': ['boardgames']},
        {'id': 17, 'names': ['science', 'nature']},
        {'id': 18, 'names': ['computers', 'computer', 'it']},
        {'id': 19, 'names': ['mathematics', 'math']},
        {'id': 20, 'names': ['mythology']},
        {'id': 21, 'names': ['sport', 'sports']},
        {'id': 22, 'names': ['geography', 'geo']},
        {'id': 23, 'names': ['history']},
        {'id': 24, 'names': ['politics']},
        {'id': 25, 'names': ['art']},
        {'id': 26, 'names': ['celebrities']},
        {'id': 27, 'names': ['animals']},
        {'id': 28, 'names': ['vehicles']},
        {'id': 29, 'names': ['comics']},
        {'id': 30, 'names': ['gadgets']},
        {'id': 31, 'names': ['anime', 'manga']},
        {'id': 32, 'names': ['cartoon', 'cartoons']},
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


class Methods(Enum):
    START = "start"
    STOP = "stop"
    # SCORE = "score"  # not impl, TODO
    # PAUSE = "pause"  # not impl, TODO
    # RESUME = "resume"  # not impl, TODO


class Modes(Enum):
    MULTIPLECHOICE = "multiplechoice",
    FREETEXT = "freetext"


class BaseQuiz(ABC):
    @abstractmethod
    def current_question(self):
        """
        Retrieves the current question.
        :return: Question object
        """
        raise NotImplemented

    @abstractmethod
    def next_question(self):
        """
        Retrieves a new question.
        :return: Question object
        """
        raise NotImplemented

    @abstractmethod
    def __del__(self):
        """
        Called when the quiz is stopped.
        :return:
        """
        raise NotImplemented


class Question:
    def __init__(self, question, correct_answer, incorrect_answers):
        self.question = question
        self.correct_answer = correct_answer
        self.incorrect_answers = incorrect_answers
        self.all_answers = incorrect_answers.append(correct_answer)
        random.shuffle(self.all_answers)

    def answers_mc(self):
        """
        :return: Generator for possible answers in a multiple-choice-fashion, e.g. "A: Jupiter"
        """
        for i in range(len(self.all_answers)):
            letter = string.ascii_uppercase[i]
            yield "{}: {}".format(letter, self.all_answers[i])

    def check_answer(self, mode, answer):
        """
        Called to check the answer to the most recent question that was retrieved via qet_question().
        :return: True if this is the first occurence of the correct answer, False otherwise
        """
        answer = answer.strip()
        if mode == Modes.MULTIPLECHOICE:
            answer = answer.lower()
            for i in range(len(string.ascii_lowercase)):
                letter = string.ascii_lowercase[i]
                if answer == letter:
                    if self.all_answers[i] == self.correct_answer:
                        return True
                    else:
                        break
            return False

        elif mode == Modes.FREETEXT:
            if answer.lower() == self.correct_answer.lower():
                # TODO improve recognition, e.g. remove whitespace, dots, determiners etc
                return True
            return False

        assert False


class OpenTDBQuiz(BaseQuiz):
    def __init__(self, ctx, config, requester, channel,
                 category=None, question_count=None, difficulty=Difficulty.EASY):
        """
        :param ctx: Message context
        :param config: config dict
        :param requester: User ID of the user that started the quiz
        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        logging.info("Beginning OpenTDBQuiz")
        self.ctx = ctx
        self.config = config
        self.channel = channel
        self.requester = requester
        self.difficulty = difficulty
        self.question_count = question_count
        if question_count is None:
            self.question_count = self.config["questions_default"]

        self.client = restclient.Client(config["base_url"])
        self.is_running = True
        self.current_question_i = -1
        self.score = {}

        self.category = None
        self.parse_category(category)
        self.questions = []

        # acquire API token
        self.token = self.client.make_request(
            config["token_route"], params={"command": "request"}, parse_json=False)["token"]

        # Acquire questions
        params = {
            "token": self.token,
            "amount": self.question_count,
            "encode": "url3986",
        }

        questions_raw = self.client.make_request(opentdb["api_route"], params=params)["results"]
        for el in questions_raw:
            question = unquote(el["question"])
            correct_answer = unquote(el["correct_answer"])
            incorrect_answers = [unquote(ia) for ia in el["incorrect_answers"]]
            self.questions.append(Question(question, correct_answer, incorrect_answers))

    def pause(self):
        self.is_running = False

    def resume(self):
        self.is_running = True

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

    def next_question(self):
        if not self.is_running:
            raise QuizNotRunning

        self.current_question_i += 1
        if self.current_question_i > len(self.questions) - 1:
            raise QuizEnded

        return self.questions[self.current_question_i]

    def current_question(self):
        return self.questions[self.current_question_i]

    def __del__(self):
        self.is_running = False


db_mapping = {
    "opentdb": OpenTDBQuiz,
}


class Plugin(commands.Cog, name="A trivia quiz"):
    def __init__(self, bot):
        self.bot = bot
        self.quizes = {}
        self.config = jsonify

        self.defaults = {
            "impl": "opentdb",
            "questions": self.config["questions_default"],
            "method": Methods.START,
            "category": None,
            "difficulty": Difficulty.EASY,
            "mode": Modes.MULTIPLECHOICE
        }

        super(commands.Cog).__init__()
        bot.register(self)

        @bot.event
        async def on_message(msg):
            # ignore DMs
            if not isinstance(msg.channel, discord.TextChannel):
                return
            quiz = self.get_quiz(msg.channel)
            if quiz is None:
                return

            check = quiz.current_question.check_answer(msg.content)
            if check:
                msg.channel.send(message(self.config, "correct_answer", "@" + msg.author.nick))
                msg.channel.send(quiz.next_question())

    @commands.command(name="kwiss", help="Interacts with the kwis subsystem.")
    async def kwiss(self, ctx):
        args = []
        logging.info("Caught kwiss cmd")
        try:
            args = self.parse_args(args)
        except QuizInitError as e:
            # Parse Error
            await ctx.send(str(e))
            return

        channel = ctx.message.channel

        # Look for existing quiz
        if args["method"] == Methods.START and self.get_quiz(channel):
            raise QuizInitError(self.config, "existing_quiz")
        if args["method"] == Methods.STOP and self.get_quiz(channel) is None:
            return

        quiz = OpenTDBQuiz(ctx, self.config, ctx.message.author, ctx.message.channel,
                           category=args["category"], question_count=args["questions"],
                           difficulty=args["difficulty"])
        self.quizes[channel] = quiz
        ctx.send(message(self.config, "quiz_start", args["questions"], args["category"],
                         args["difficulty"], message(self.config, args["mode"].value)))
        ctx.send(quiz.next_question())

    def get_quiz(self, channel):
        """
        Retrieves the running quiz in a channel.
        :param channel: Channel that is checked for.
        :return: Quiz object that is running in channel. None if no quiz is running in channel.
        """
        if channel in self.quizes:
            return self.quizes[channel]
        return None

    def parse_args(self, args):
        """
        Parses the arguments given to the quiz command and fills in defaults if necessary.
        :param args: argument list
        :return: Dict with the parsed arguments
        """
        found = {el: False for el in self.defaults}
        parsed = self.defaults.copy()

        for arg in args:
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
                if arg.lower() == db:
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

            # category: opentdb
            for mapping in opentdb["cat_mapping"]:
                for cat in mapping["names"]:
                    if arg.lower() == cat:
                        if found["category"]:
                            raise QuizInitError(self.config, "dupiclate_cat_arg")
                        parsed["category"] = (mapping["id"], "opentdb")
                        found["category"] = True
            if found["category"]:
                continue

            raise QuizInitError(self.config, "unknown_arg", arg)
        return parsed
