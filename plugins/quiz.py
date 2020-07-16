import string
import random
import logging
import warnings
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from urllib.parse import unquote

import discord
from discord.ext import commands

import Geckarbot
from conf import Config
from botutils import restclient, utils, permChecks, statemachine
from subsystems.reactions import ReactionRemovedEvent

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

reactions = {
    "signup": "📋",
    "correct": "✅",
    "incorrect": "❌",
}

msg_defaults = {
    "and": "and",
    "nobody": "Nobody",
    "unknown_arg": "Unknown argument: {}",
    "too_many_questions": "Sorry, too many questions. Limit is {}",
    "duplicate_count_arg": "You defined how many questions you want more than once. Make up your mind.",
    "duplicate_db_arg": "You defined which database you want more than once. Make up your mind.",
    "duplicate_method_arg": "You defined what you want me to do more than once. Make up your mind.",
    "duplicate_cat_arg": "Sorry, specifying more than one argument is not supported.",
    "duplicate_difficulty_arg": "You defined the difficulty more than once. Make up your mind.",
    "duplicate_mode_arg": "You defined the answering mode more than once. Make up your mind.",
    "duplicate_controller_arg": "You defined the game mode more than once. Make up your mind.",
    "too_many_arguments": "Too many arguments.",
    "invalid_argument": "Invalid argument: {}",
    "existing_quiz": "There is already a kwiss running in this channel.",

    "correct_answer": "{}: {} is the correct answer!",
    "quiz_start": "Starting kwiss! {} questions. Category: {}. Difficulty: {}. Game Mode: {}",
    "quiz_end": "The kwiss has ended. The winner is: **{}**! Congratulations!",
    "quiz_end_pl": "The kwiss has ended. The winners are: **{}**! Congratulations!",
    "quiz_end_no_winner": "The kwiss has ended. The winner is: **{}**! Congratulations, you suck!",
    "quiz_abort": "The kwiss was aborted.",
    "answering_order": "{}: Please let someone else answer first.",
    "registering_phase": "Please register for the upcoming kwiss via a {} reaction. I will wait {} minute."
                         .format(reactions["signup"], "{}"),
    "registering_too_late": "{}: Sorry, too late. The kwiss has already begun.",
    "register_success": "{}: You're in!",
    "quiz_phase": "The kwiss will begin in 10 seconds!",
    "points_question_done": "The correct answer was {}!\n{} answered correctly.",
    "points_timeout_warning": "Waiting for answers from {}. You have {} seconds!",
    "points_timeout": "Timeout!",
    "status_no_quiz": "There is no kwiss running in this channel.",
    "results_title": "Results:",
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
        {'id': 14, 'names': ['T.V.', 'tv', 'television']},
        {'id': 15, 'names': ['Games', 'games']},
        {'id': 16, 'names': ['Boardgames', 'boardgames']},
        {'id': 17, 'names': ['Science / Nature', 'science', 'nature']},
        {'id': 18, 'names': ['Computers', 'computers', 'computer', 'it']},
        {'id': 19, 'names': ['Mathematics', 'mathematics', 'math']},
        {'id': 20, 'names': ['Mythology', 'mythology']},
        {'id': 21, 'names': ['Sports', 'sports', 'sport']},
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
        {'id': 32, 'names': ['Cartoons / Animated', 'cartoons', 'cartoon', 'animated']},
    ]
}


def uemoji(config, user):
    if not isinstance(user, int):
        user = user.id
    if user in config["emoji"]:
        return "{} ".format(config["emoji"][user])
    return ""


def get_best_username(config, user):
    return "{}{}".format(uemoji(config, user), utils.get_best_username(user))


def message(config, msg_id, *args):
    """
    Builds a message out of configured messages and defaults.
    :param config: Config dict
    :param msg_id: Message key out of msg_defaults
    :param args: Format string args
    :return: Compiled message
    """
    if len(args) == 0:
        args = [""]  # ugly lol

    msg = msg_id
    if msg_id in config:
        msg = config[msg_id].format(*args)
    elif msg_id in msg_defaults:
        msg = msg_defaults[msg_id].format(*args)
    return msg


def dummy(el):
    return el


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


class SubCommandEncountered(Exception):
    def __init__(self, callback, args):
        super().__init__()
        self.callback = callback
        self.args = args


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

    def __len__(self):
        """
        :return: Returns the amount of questions.
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
    async def start(self, msg):
        """
        Called when the start command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def pause(self, msg):
        """
        Called when the pause command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def resume(self, msg):
        """
        Called when the resume command is invoked.
        """
        raise NotImplementedError

    @abstractmethod
    async def status(self, msg):
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
    def abort(self, msg):
        """
        Called when the quiz is aborted.
        """
        pass


class Score:
    def __init__(self, plugin, config, question_count):
        self._score = {}
        self._points = {}
        self.plugin = plugin
        self.config = config
        self.question_count = question_count
        self.answered_questions = []

        self.interpol_x = [0, 10, 35, 55, 75, 100]
        self.interpol_y = [0, 30, 60, 75, 88, 100]
        self.dd = self.divdiff(self.interpol_x, self.interpol_y)

    @staticmethod
    def divdiff(x, f):
        r = []
        for _ in range(len(x)):
            r.append([0] * len(x))
        for i in range(len(r)):
            for k in range(len(r)):
                # first column
                if i == 0:
                    r[i][k] = f[k]
                    continue
                # 0-triangle
                if i + k >= len(r):
                    continue
                a = r[i - 1][k + 1] - r[i - 1][k]
                b = x[k + i] - x[k]
                r[i][k] = a / b

        return r

    def f(self, a):
        """
        Function that is applied to every calculated score to improve the spread.
        :param a: Score value to be improved
        :return: Value between 0 and 100
        """
        r = self.dd[len(self.dd) - 1][0]
        for i in range(len(self.interpol_x) - 2, -1, -1):
            r = r * (a - self.interpol_x[i]) + self.dd[i][0]
        return r

    def calc_points(self, user):
        """
        :param user: The user whose points are to be calculated
        :return: user's points
        """
        if user not in self._score:
            raise KeyError("User {} not found in score".format(user))

        return int(round(self.f(100 * self._points[user] * (1 - 1/len(self.answered_questions)))))

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

    def ladder(self, sort_by_points=False):
        """
        :return: List of members in score, sorted by score or points, depending on sort_by_points
        """
        firstsort = self._score
        secondsort = self.points()
        if sort_by_points:
            firstsort = secondsort
            secondsort = self._score

        # two-step sorting
        s = {}
        for user in firstsort:
            if firstsort[user] in s:
                s[firstsort[user]].append(user)
            else:
                s[firstsort[user]] = [user]
        for score in s:
            s[score] = sorted(s[score], key=lambda x: secondsort[x], reverse=True)
        keys = sorted(s.keys(), reverse=True)

        # flatten
        r = []
        for key in keys:
            for user in s[key]:
                r.append(user)
        return r

    def winners(self):
        """
        :return: Return list of winners
        """
        r = []
        lastscore = None
        for el in self.ladder():
            if self._score[el] == 0:
                break
            elif lastscore is None:
                r.append(el)
                lastscore = self._score[el]
            elif lastscore == self._score[el]:
                r.append(el)
            elif lastscore > self._score[el]:
                break
            else:
                assert False
        return r

    def embed(self, end=False, sort_by_points=False):
        embed = discord.Embed(title=message(self.config, "results_title"))

        ladder = self.ladder(sort_by_points=sort_by_points)
        place = 0
        for i in range(len(ladder)):
            user = ladder[i]
            if i == 0 or self._score[user] < self._score[ladder[i - 1]]:
                place += 1

            # embed
            name = "**#{}** {}".format(place, get_best_username(Config().get(self.plugin), user))
            value = "Correct answers: {}".format(self._score[user])
            if len(self) > 1:
                value = "{}\nScore: {}".format(value, self.calc_points(user))
            embed.add_field(name=name, value=value)

            i += 1

        if len(ladder) == 0:
            if end:
                embed.add_field(name="Nobody has scored!", value=" ")
            else:
                embed.add_field(name="**#1** Geckarbot", value="I won! :)")

        return embed

    def increase(self, member, question, amount=1, totalcorr=1,):
        """
        Increases a participant's score by amount. Registers the participant if not present.
        :param member: Discord member
        :param amount: Amount to increase the member's score by; defaults to 1.
        :param totalcorr: Total amount of correct answers to the question
        :param question: Question object (to determine the amount of questions correctly answered)
        """
        # Increment user score
        if member not in self._score:
            self.add_participant(member)
        self._score[member] += amount
        self._points[member] += amount / totalcorr / self.question_count

        # Handle list of answered questions
        if question is not None:
            if self.answered_questions is None:
                self.answered_questions = [question]
            elif question not in self.answered_questions:
                self.answered_questions.append(question)

    def add_participant(self, member):
        if member not in self._score:
            self._score[member] = 0
            self._points[member] = 0
        else:
            logging.getLogger(__name__).warning("Adding {} to score who was already there. This should not happen.")

    def __len__(self):
        return len(self._score)


class InvalidAnswer(Exception):
    pass


class Question:
    def __init__(self, question, correct_answer, incorrect_answers, index=None):
        logging.debug("Question({}, {}, {})".format(question, correct_answer, incorrect_answers))
        self.index = index

        self.question = question
        self.correct_answer = correct_answer
        self.incorrect_answers = incorrect_answers

        self.all_answers = incorrect_answers.copy()
        self.all_answers.append(correct_answer)
        random.shuffle(self.all_answers)

        self._cached_emoji = None
        self.message = None

        # Set emoji and letter format of correct answer
        self.correct_answer_emoji = None
        self.correct_answer_letter = None
        for i in range(len(self.all_answers)):
            if self.correct_answer == self.all_answers[i]:
                e = self.letter_mapping(i, emoji=True, reverse=False)
                letter = self.letter_mapping(i, emoji=False, reverse=False)
                self.correct_answer_emoji = "{} {}".format(e, self.correct_answer)
                self.correct_answer_letter = "**{}:** {}".format(letter, self.correct_answer)
                break

    def letter_mapping(self, index, emoji=False, reverse=False):
        if not reverse:
            if emoji:
                return self.emoji_map[index]
            else:
                return string.ascii_uppercase[index]

        # Reverse
        if emoji:
            haystack = self.emoji_map
        else:
            index = index.lower()
            haystack = string.ascii_lowercase

        for i in range(len(haystack)):
            if str(index) == str(haystack[i]):
                return i
        return None

    async def pose(self, channel, emoji=False):
        logging.getLogger(__name__).debug("Posing question #{}: {}".format(self.index, self.question))
        msg = await channel.send(embed=self.embed(emoji=emoji))
        if emoji:
            for i in range(len(self.all_answers)):
                await msg.add_reaction(Config().EMOJI["lettermap"][i])  # this breaks if there are more than 26 answers
        self.message = msg
        return msg

    def embed(self, emoji=False):
        """
        :return: An embed representation of the question.
        """
        title = self.question
        if self.index is not None:
            title = "#{}: {}".format(self.index+1, title)
        embed = discord.Embed(title=title)
        value = "\n".join([el for el in self.answers_mc(emoji=emoji)])
        embed.add_field(name="Possible answers:", value=value)
        return embed

    def answers_mc(self, emoji=False):
        """
        :param emoji: If True, uses unicode emoji letters instead of regular uppercase letters
        :return: Generator for possible answers in a multiple-choice-fashion, e.g. "A: Jupiter"
        """
        for i in range(len(self.all_answers)):
            if emoji:
                letter = "{}".format(self.letter_mapping(i, emoji=emoji))
            else:
                letter = "**{}:**".format(self.letter_mapping(i, emoji=emoji))
            yield "{} {}".format(letter, self.all_answers[i])

    def check_answer(self, answer, emoji=False):
        """
        Called to check the answer to the most recent question that was retrieved via qet_question().
        :return: True if this is the first occurence of the correct answer, False otherwise
        """
        if answer is None:
            return False

        if not emoji:
            answer = answer.strip().lower()
        i = self.letter_mapping(answer, emoji=emoji, reverse=True)

        if i is None:
            raise InvalidAnswer()
        elif self.all_answers[i] == self.correct_answer:
            return True
        else:
            return False

    @property
    def emoji_map(self):
        if self._cached_emoji is None:
            self._cached_emoji = Config().EMOJI["lettermap"][:len(self.all_answers)]
        return self._cached_emoji

    def is_valid_emoji(self, emoji):
        for el in self.emoji_map:
            if el == emoji:
                return True
        return False


class Phases(Enum):
    INIT = 0
    REGISTERING = 1
    ABOUTTOSTART = 2
    QUESTION = 3
    EVAL = 4
    END = 5
    ABORT = 6


class PointsQuizController(BaseQuizController):
    """
    Gamemode: every user with the correct answer gets a point
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
        plugin.logger.debug("Building PointsQuizController; kwargs: {}".format(kwargs))
        self.cmdstring_register = "register"

        self.channel = channel
        self.requester = requester
        self.config = config
        self.plugin = plugin

        # QuizAPI config
        self.category = None
        if "category" in kwargs:
            self.category = kwargs["category"]
        self.debug = False
        if "debug" in kwargs and kwargs["debug"]:
            self.debug = True
        self.question_count = kwargs["question_count"]
        self.difficulty = kwargs["difficulty"]

        self.quizapi = quizapi
        self._score = Score(self.plugin, self.config, self.question_count)

        # State handling
        self.ran_into_timeout = False
        self.current_question = None
        self.current_question_timer = None
        self.current_reaction_listener = None
        self.statemachine = statemachine.StateMachine()
        self.statemachine.add_state(Phases.INIT, None, None)
        self.statemachine.add_state(Phases.REGISTERING, self.start_registering_phase, [Phases.INIT])
        self.statemachine.add_state(Phases.ABOUTTOSTART, self.about_to_start, [Phases.REGISTERING])
        self.statemachine.add_state(Phases.QUESTION, self.pose_question, [Phases.ABOUTTOSTART, Phases.EVAL])
        self.statemachine.add_state(Phases.EVAL, self.eval, [Phases.QUESTION])
        self.statemachine.add_state(Phases.END, self.end, [Phases.QUESTION], end=True)
        self.statemachine.add_state(Phases.ABORT, self.abortphase, None, end=True)
        self.statemachine.state = Phases.INIT

        # Participant handling
        self.registered_participants = {}

    """
    Transitions
    """
    async def start_registering_phase(self):
        """
        REGISTERING -> ABOUTTOSTART; REGISTERING -> ABORT
        """
        self.plugin.logger.debug("Starting PointsQuizController")
        self.state = Phases.REGISTERING
        signup_msg = await self.channel.send(message(self.config, "registering_phase",
                                                     self.config["points_quiz_register_timeout"] // 60))
        await signup_msg.add_reaction(reactions["signup"])

        await asyncio.sleep(self.config["points_quiz_register_timeout"])

        # Consume signup reactions
        await signup_msg.remove_reaction(reactions["signup"], self.plugin.bot.user)
        signup_msg = discord.utils.get(self.plugin.bot.cached_messages, id=signup_msg.id)
        reaction = None
        for el in signup_msg.reactions:
            if el.emoji == reactions["signup"]:
                reaction = el
                break

        if reaction is not None:
            async for user in reaction.users():
                if user == self.plugin.bot.user:
                    continue

                found = False
                for el in self.registered_participants:
                    if el == user:
                        found = True
                        break
                if found:
                    # User already registered via !kwiss register
                    continue

                self.registered_participants[user] = []
            if self.debug:
                self.registered_participants[self.plugin.bot.user] = []

        if len(self.registered_participants) == 0:
            self.state = Phases.ABORT
        else:
            self.state = Phases.ABOUTTOSTART

    async def about_to_start(self):
        """
        ABOUTTOSTART -> QUESTION; ABOUTTOSTART -> ABORT
        """
        self.plugin.logger.debug("Ending the registering phase")

        if len(self.registered_participants) == 0:
            embed, msg = self.plugin.end_quiz(self.channel)
            self.channel.send(msg, embed=embed)
            return
        else:
            embed = discord.Embed(title=message(self.config, "quiz_phase"))
            value = "\n".join(["{}{}".format(uemoji(Config().get(self.plugin), el), el.mention)
                               for el in self.registered_participants])
            embed.add_field(name="Participants:", value=value)
            await self.channel.send(embed=embed)

        await asyncio.sleep(10)
        self.state = Phases.QUESTION

    async def pose_question(self):
        """
        QUESTION -> EVAL; QUESTION -> END
        """
        self.plugin.logger.debug("Posing next question.")
        try:
            self.current_question = self.quizapi.next_question()
        except QuizEnded:
            self.plugin.logger.debug("Caught QuizEnded, will end the quiz now.")
            self.state = Phases.END
            return

        self.current_question_timer = utils.AsyncTimer(self.plugin.bot, self.config["points_quiz_question_timeout"],
                                                       self.timeout_warning, self.current_question)
        msg = await self.current_question.pose(self.channel, emoji=self.config["emoji_in_pose"])
        self.current_reaction_listener = self.plugin.bot.reaction_listener.register(
            msg, self.on_reaction, data=self.current_question)

    async def eval(self):
        """
        Is called when the question is over. Evaluates scores and cancels the timer.
        :return:
        """
        self.plugin.logger.debug("Ending question")

        # If debug, add bot's answer
        if self.debug:
            self.plugin.logger.debug("Adding bot's answer")
            found = None
            for i in range(len(self.current_question.all_answers)):
                print("Comparing {} and {}".format(self.current_question.all_answers[i],
                                                   self.current_question.correct_answer))
                if self.current_question.all_answers[i] == self.current_question.correct_answer:
                    found = i
                    break
            self.registered_participants[self.plugin.bot.user] = self.current_question.letter_mapping(found, emoji=True)

        # End timeout timer
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except utils.HasAlreadyRun:
                self.plugin.logger.warning("This should really, really not happen.")
            self.current_question_timer = None
        else:
            # We ran into a timeout and need to give that function time to communicate this fact
            await asyncio.sleep(1)

        if self.current_reaction_listener is not None:
            self.current_reaction_listener.unregister()

        question = self.quizapi.current_question()

        # Normalize answers
        for el in self.registered_participants:
            if len(self.registered_participants[el]) != 1:
                self.registered_participants[el] = None
            else:
                self.registered_participants[el] = self.registered_participants[el][0]

        # Increment scores
        correctly_answered = []
        for user in self.registered_participants:
            if question.check_answer(self.registered_participants[user], emoji=True):
                correctly_answered.append(user)

        for user in correctly_answered:
            self.score.increase(user, self.current_question, totalcorr=len(correctly_answered))

        correct = [get_best_username(Config().get(self.plugin), el) for el in correctly_answered]
        correct = utils.format_andlist(correct, message(self.config, "and"), message(self.config, "nobody"))
        if self.config["emoji_in_pose"]:
            ca = question.correct_answer_emoji
        else:
            ca = question.correct_answer_letter
        await self.channel.send(message(self.config, "points_question_done", ca, correct))

        # Reset answers list
        for user in self.registered_participants:
            self.registered_participants[user] = []

        await asyncio.sleep(self.config["question_cooldown"])
        self.state = Phases.QUESTION

    async def end(self):

        embed = self.score.embed()
        winners = [get_best_username(Config().get(self.plugin), x) for x in self.score.winners()]

        msgkey = "quiz_end"
        if len(winners) > 1:
            msgkey = "quiz_end_pl"
        elif len(winners) == 0:
            msgkey = "quiz_end_no_winner"
        winners = utils.format_andlist(winners, ands=message(self.config, "and"),
                                       emptylist=message(self.config, "nobody"))
        msg = message(self.config, msgkey, winners)
        if msg is None:
            await self.channel.send(embed=embed)
        elif embed is None:
            await self.channel.send(msg)
        else:
            await self.channel.send(msg, embed=embed)

        self.plugin.end_quiz(self.channel)

    async def abortphase(self):
        self.plugin.end_quiz(self.channel)
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except utils.HasAlreadyRun:
                pass
        await self.channel.send("The quiz was aborted.")

    """
    Callbacks
    """
    async def on_message(self, msg):
        return

    async def on_reaction(self, event):
        self.plugin.logger.debug("Caught reaction: {} on {}".format(event.emoji, event.message))

        # Cases we don't care about
        if self.state != Phases.QUESTION or self.current_question != event.data:
            return
        if event.member not in self.registered_participants:
            return

        if isinstance(event, ReactionRemovedEvent):
            self.registered_participants[event.member].remove(event.emoji)
            return

        try:
            check = self.quizapi.current_question().check_answer(event.emoji, emoji=True)
            if check:
                check = "correct"
            else:
                check = "incorrect"
            self.plugin.logger.debug("Valid answer from {}: {} ({})"
                                     .format(event.member.name, event.emoji, check))
        except InvalidAnswer:
            return

        self.registered_participants[event.member].append(event.emoji)
        if self.has_everyone_answered():
            self.state = Phases.EVAL

    """
    Timers stuff; these functions are scheduled by timers only
    """
    async def timeout_warning(self, question):
        """
        :param question: Question object of the question that was running at timer start time.
        """
        if self.current_question != question or self.state != Phases.QUESTION:
            # We are out of date
            self.plugin.logger.debug("Timeout warning out of date")
            return

        self.plugin.logger.debug("Question timeout warning")
        self.current_question_timer = utils.AsyncTimer(self.plugin.bot,
                                                       self.config["points_quiz_question_timeout"] // 2,
                                                       self.timeout, self.current_question)

        await self.channel.send(message(self.config, "points_timeout_warning",
                                        utils.format_andlist(self.havent_answered_hr(),
                                                             ands=message(self.config, "and")),
                                        self.config["points_quiz_question_timeout"] // 2))

    async def timeout(self, question):
        """
        :param question: Question object of the question that was running at timer start time.
        """
        if self.current_question != question or self.state != Phases.QUESTION:
            # We are out of date
            self.plugin.logger.debug("Timeout warning out of date")
            return

        self.current_question_timer = None
        self.plugin.logger.debug("Question timeout")
        msg = message(self.config, "points_timeout", self.quizapi.current_question_index(),
                      utils.format_andlist(self.havent_answered_hr(), ands=message(self.config, "and")))
        self.state = Phases.EVAL
        await self.channel.send(msg)

    """
    Commands
    """
    async def start(self, msg):
        """
        Called when the start command is invoked.
        """
        # Fetch questions
        self.quizapi = self.quizapi(self.config, self.channel,
                                    category=self.category, question_count=self.question_count,
                                    difficulty=self.difficulty, debug=self.debug)
        self.state = Phases.REGISTERING

    async def register_command(self, msg, *args):
        """
        This is the callback for !kwiss register.
        :param msg: Message object
        :param args: Passed arguments, including "register"
        """
        assert self.cmdstring_register in args
        if "skip" in args:
            self.state = Phases.ABOUTTOSTART
            return

        if len(args) > 1:
            await self.channel.send(message(self.config, "too_many_arguments"))
            return

        if self.state == Phases.INIT:
            await self.channel.send("No idea how you did that, but you registered too early.")
            return

        if self.state != Phases.REGISTERING:
            await self.channel.send(message(self.config, "registering_too_late", msg.author))
            return

        if msg.author in self.registered_participants:
            return

        self.registered_participants[msg.author] = []
        self.score.add_participant(msg.author)
        self.plugin.logger.debug("{} registered".format(msg.author.name))
        await msg.add_reaction(Config().CMDSUCCESS)
        # await self.channel.send(message(self.config, "register_success", msg.author))

    async def pause(self, msg):
        """
        Called when the pause command is invoked.
        """
        raise NotImplementedError

    async def resume(self, msg):
        """
        Called when the resume command is invoked.
        """
        raise NotImplementedError

    async def status(self, msg):
        """
        Called when the status command is invoked.
        """
        embed = discord.Embed(title="Kwiss: question {}/{}".format(
            self.quizapi.current_question_index() + 1, len(self.quizapi)))
        embed.add_field(name="Category", value=self.quizapi.category_name(self.category))
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Points (Everyone answers)")
        embed.add_field(name="Initiated by", value=get_best_username(Config().get(self.plugin), self.requester))

        status = ":arrow_forward: Running"
        if self.state == Phases.REGISTERING:
            status = ":book: Signup phase"
        #    status = ":pause_button: Paused"
        embed.add_field(name="Status", value=status)

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        await self.channel.send(embed=embed)

    async def abort(self, msg):
        """
        Called when the quiz is aborted.
        """
        self.state = Phases.ABORT
        await msg.add_reaction(Config().CMDSUCCESS)

    @property
    def score(self):
        """
        :return: Score object
        """
        return self._score

    """
    Utils
    """
    @property
    def state(self):
        return self.statemachine.state

    @state.setter
    def state(self, state):
        self.statemachine.state = state

    def has_everyone_answered(self):
        for el in self.registered_participants:
            if len(self.registered_participants[el]) != 1:
                return False

        return True

    def havent_answered_hr(self):
        return [get_best_username(Config().get(self.plugin), el)
                for el in self.registered_participants if len(self.registered_participants[el]) != 1]


class RushQuizController(BaseQuizController):
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
        plugin.logger.debug("Building RaceQuizController; kwargs: {}".format(kwargs))
        self.config = config
        self.plugin = plugin
        self.channel = channel
        self.requester = requester

        # QuizAPI config
        self.category = None
        if "category" in kwargs:
            self.category = kwargs["category"]
        self.debug = False
        if "debug" in kwargs and kwargs["debug"]:
            self.debug = True
        self.question_count = kwargs["question_count"]
        self.difficulty = kwargs["difficulty"]

        # State handling
        self.current_question = None
        self.current_question_timer = None
        self.statemachine = statemachine.StateMachine()
        self.statemachine.add_state(Phases.INIT, None, None)
        self.statemachine.add_state(Phases.ABOUTTOSTART, self.about_to_start, [Phases.INIT])
        self.statemachine.add_state(Phases.QUESTION, self.pose_question, [Phases.ABOUTTOSTART, Phases.EVAL])
        self.statemachine.add_state(Phases.EVAL, self.eval, [Phases.QUESTION])
        self.statemachine.add_state(Phases.END, self.end, [Phases.QUESTION], end=True)
        self.statemachine.add_state(Phases.ABORT, self.abortphase, None, end=True)
        self.statemachine.state = Phases.INIT

        # Quiz handling
        self.last_author = None
        self.quizapi = quizapi
        self._score = Score(self.plugin, self.config, self.question_count)

    """
    Transitions
    """
    async def about_to_start(self):
        await self.channel.send(message(self.config, "quiz_phase"))
        await asyncio.sleep(10)
        self.state = Phases.QUESTION

    async def pose_question(self):
        """
        QUESTION -> EVAL
        """
        self.last_author = None
        self.plugin.logger.debug("Posing next question.")
        try:
            self.current_question = self.quizapi.next_question()
        except QuizEnded:
            self.plugin.logger.debug("Caught QuizEnded, will end the quiz now.")
            self.state = Phases.END
            return
        await self.current_question.pose(self.channel)

    async def eval(self):
        """
        Is called when the question is over. Evaluates scores and cancels the timer.
        :return:
        """
        self.plugin.logger.debug("Ending question")

        question = self.quizapi.current_question()

        # Increment score
        self.score.increase(self.last_author, question)
        await self.channel.send(message(self.config, "correct_answer",
                                        get_best_username(Config().get(self.plugin), self.last_author),
                                        question.correct_answer_letter))

        await asyncio.sleep(self.config["question_cooldown"])
        self.state = Phases.QUESTION

    async def end(self):

        embed = self.score.embed()
        winners = [get_best_username(Config().get(self.plugin), x) for x in self.score.winners()]

        # Übergangslösung
        points = self.score.points()
        for user in points:
            self.plugin.update_ladder(user, points[user])

        msgkey = "quiz_end"
        if len(winners) > 1:
            msgkey = "quiz_end_pl"
        elif len(winners) == 0:
            msgkey = "quiz_end_no_winner"
        winners = utils.format_andlist(winners, ands=message(self.config, "and"),
                                       emptylist=message(self.config, "nobody"))
        msg = message(self.config, msgkey, winners)

        if msg is None:
            await self.channel.send(embed=embed)
        elif embed is None:
            await self.channel.send(msg)
        else:
            await self.channel.send(msg, embed=embed)

        self.plugin.end_quiz(self.channel)

    async def on_message(self, msg):
        self.plugin.logger.debug("Caught message: {}".format(msg.content))
        # ignore DM and msg when the quiz is not in question phase
        if not isinstance(msg.channel, discord.TextChannel):
            return
        if self.state != Phases.QUESTION:
            self.plugin.logger.debug("Ignoring message, quiz is not in question phase")
            return

        # Valid answer
        try:
            check = self.quizapi.current_question().check_answer(msg.content)
            if check:
                reaction = "correct"
            else:
                reaction = "incorrect"
            self.plugin.logger.debug("Valid answer from {}: {} ({})".format(msg.author.name, msg.content, reaction))
        except InvalidAnswer:
            return

        if not self.debug and self.last_author == msg.author:
            await msg.channel.send(message(self.config, "answering_order", msg.author))
            return

        self.last_author = msg.author
        if check:
            self.state = Phases.EVAL
        await msg.add_reaction(reactions[reaction])

    async def abortphase(self):
        await self.channel.send("The quiz was aborted.")
        self.plugin.end_quiz(self.channel)

    """
    Commands
    """
    async def start(self, msg):
        self.quizapi = self.quizapi(self.config, self.channel,
                                    category=self.category, question_count=self.question_count,
                                    difficulty=self.difficulty, debug=self.debug)
        self.state = Phases.ABOUTTOSTART

    async def pause(self, msg):
        raise NotImplementedError

    async def resume(self, msg):
        raise NotImplementedError

    async def status(self, msg):
        embed = discord.Embed(title="Kwiss: question {}/{}".format(
            self.quizapi.current_question_index() + 1, len(self.quizapi)))
        embed.add_field(name="Category", value=self.quizapi.category_name(self.category))
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Rush (Winner takes it all)")
        embed.add_field(name="Initiated by", value=get_best_username(Config().get(self.plugin), self.requester))

        status = ":arrow_forward: Running"
        #    status = ":pause_button: Paused"
        embed.add_field(name="Status", value=status)

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        await msg.add_reaction(Config().CMDSUCCESS)
        await self.channel.send(embed=embed)

    @property
    def score(self):
        return self._score

    def stop(self):
        pass

    async def abort(self, msg):
        self.state = Phases.ABORT
        await msg.add_reaction(Config().CMDSUCCESS)

    """
    Utils
    """
    @property
    def state(self):
        return self.statemachine.state

    @state.setter
    def state(self, state):
        self.statemachine.state = state


class OpenTDBQuizAPI(BaseQuizAPI):
    def __init__(self, config, channel,
                 category=None, question_count=None, difficulty=Difficulty.EASY,
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
        for i in range(len(questions_raw)):
            el = questions_raw[i]
            question = discord.utils.escape_markdown(unquote(el["question"]))
            correct_answer = discord.utils.escape_markdown(unquote(el["correct_answer"]))
            incorrect_answers = [discord.utils.escape_markdown(unquote(ia)) for ia in el["incorrect_answers"]]
            self.questions.append(Question(question, correct_answer, incorrect_answers, index=i))

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

    @staticmethod
    def category_name(catkey):
        """
        :return: Human-readable representation of the quiz category
        """
        for el in opentdb["cat_mapping"]:
            if el["id"] == catkey:
                return el["names"][0]
        return catkey

    def cat_count(self, cat):
        found = None
        for el in opentdb["cat_mapping"]:
            if cat in opentdb["cat_mapping"][el]:
                found = el
                break
        if found == -1:
            return -1
        params = {"category": cat}
        self.client.make_request("api_count.php", params=params)

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

    def __len__(self):
        return len(self.questions)

    def __del__(self):
        self.is_running = False


db_mapping = {
    "opentdb": OpenTDBQuizAPI,
}


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
            "difficulty": Difficulty.EASY,
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
            await msg.channel.send(message(self.config, "too_many_arguments"))
            return

        embed = discord.Embed(title="Categories:")
        s = []
        for el in opentdb["cat_mapping"]:
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
        """
        :return: Embed that represents the rank ladder
        """
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
            await ctx.send(message(self.config, err))
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
            raise QuizInitError(self.config, "existing_quiz")
        if modifying and self.get_controller(channel) is None:
            if method == Methods.STATUS:
                await ctx.send(message(self.config, "status_no_quiz"))
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
        await ctx.send(message(self.config, "quiz_start", args["questions"],
                               OpenTDBQuizAPI.category_name(args["category"]),
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
                        raise QuizInitError(self.config, "duplicate_subcmd_arg")
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

            # controller
            for el in self.controller_mapping:
                if arg in self.controller_mapping[el]:
                    if controller_found:
                        raise QuizInitError(self.config, "duplicate_controller_arg")
                    controller = el
                    controller_found = True
                    break
            if controller_found:
                continue

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

            raise QuizInitError(self.config, "unknown_arg", arg)

        self.logger.debug("Parsed kwiss args: {}".format(parsed))
        return controller, parsed
