from discord.ext import commands
from botUtils import restclient
from abc import ABC, abstractmethod
from enum import Enum


jsonify = {
    "timeout": 20,  # answering timeout in minutes
    "timeout_warning": 2,  # warning time before timeout in minutes
    "questions_limit": 50,
    "questions_default": 20,
    "unknown_cat": "Unbekannte Kategorie: {}",
    "too_many_questions": "Zuviele Fragen. Das Limit ist {}.",
}

msg_defaults = {
    "unknown_cat": "Unknown category: {}",
    "too_many_questions": "Sorry, too many questions. Limit is {}",
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
        {'id': 21, 'names': ['sports']},
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


class QuizConstructionError(Exception):
    def __init__(self, config, msg_id, *args):
        msg = msg_id
        if msg_id in config:
            msg = config[msg_id].format(*args)
        elif msg_id in msg_defaults:
            msg = msg_defaults[msg_id].format(*args)
        super().__init__(msg)


class QuizEnded(Exception):
    """
    To be raised by the Quiz class on get_question() if the quiz has ended (for whatever reason)
    """
    pass


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class BaseQuiz(ABC):
    @abstractmethod
    def get_question(self):
        """
        Retrieves a new question.
        :return: String that contains the question.
        """
        raise NotImplemented

    @abstractmethod
    def check_answer(self, answer):
        """
        Called to check the answer to the most recent question that was retrieved via qet_question().
        :return: True if this is the first occurence of the correct answer, False otherwise
        """
        raise NotImplemented

    @abstractmethod
    def __del__(self):
        """
        Called when the quiz is stopped.
        :return:
        """
        raise NotImplemented


class OpenTDBQuiz(BaseQuiz):
    def __init__(self, config, requester, channel, category=None, question_count=None, difficulty=Difficulty.MEDIUM):
        """
        :param config: config dict
        :param requester: User ID of the user that started the quiz
        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        self.config = config
        self.channel = channel
        self.requester = requester
        self.difficulty = difficulty
        self.question_count = question_count
        if question_count is None:
            self.question_count = self.config["questions_default"]
        if question_count > self.config["questions_limit"]:
            raise QuizConstructionError(self.config, "too_many_questions", question_count)

        self.client = restclient.Client(config["base_url"])
        self.current_question = None
        self.current_answer = None

        self.category = None
        self.parse_category(category)

        # acquire API token
        self.token = self.client.make_request(
            config["token_route"], params={"command": "request"}, parse_json=False)["token"]

    def parse_category(self, cat):
        """
        Takes all available info to determine the correct category.
        :param cat: Category that was given by User. None if none was given.
        :return:
        """
        # Category was given; finding corresponding ID
        if cat is not None:
            for el in opentdb["cat_mapping"]:
                if cat.lower() in el["names"]:
                    self.category = el["id"]
                    return

            raise QuizConstructionError(self.config["unknown_cat"].format(cat))

        # Category was not given, this is where the fun begins TODO
        raise NotImplemented

    def get_question(self):
        pass

    def check_answer(self, answer):
        # In between questions
        if self.current_question is None:
            return False
        pass

    def __del__(self):
        pass


class Plugin(commands.Cog, name="A trivia quiz"):
    def __init__(self, bot):
        self.bot = bot
        self.quizes = {}

        super(commands.Cog).__init__()
        bot.register(self)

        @bot.event
        async def on_message(message):
            pass
