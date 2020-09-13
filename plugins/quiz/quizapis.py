import logging
from urllib.parse import unquote
import random

import discord

from botutils import restclient

from plugins.quiz.abc import BaseQuizAPI
from plugins.quiz.controllers import QuizEnded
from plugins.quiz.base import Difficulty, Question, CategoryKey

opentdb = {
    "base_url": "https://opentdb.com",
    "token_route": "api_token.php",
    "api_route": "api.php",
    "api_count_route": "api_count.php",
    "default_cat": "any",
    "cat_mapping": [
        {'id': -1, 'names': ['Any', 'any', 'none', 'all', 'null']},
        {'id': 9, 'names': ['General', 'general']},
        {'id': 10, 'names': ['Books', 'books']},
        {'id': 11, 'names': ['Film', 'film']},
        {'id': 12, 'names': ['Music', 'music']},
        {'id': 13, 'names': ['Musical / Theatre', 'musical', 'musicals',
                             'theatres', 'theatre', 'theater', 'theaters']},
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

        self.category = category
        self.questions = []

        # Acquire API token
        self.token = self.client.make_request(opentdb["token_route"], params={"command": "request"})
        self.token = self.token["token"]

        # Build request params
        params = {
            "token": self.token,
            "amount": self.question_count,
            "encode": "url3986",
            "type": "multiple",
        }
        if self.category is None:
            self.category = self.category_key(self.category)
        print("CATEGORY: {}".format(self.category))
        catkey, _ = self.category.get(OpenTDBQuizAPI)
        if catkey > 0:
            params["category"] = catkey
        if self.difficulty != Difficulty.ANY:
            params["difficulty"] = self.difficulty.value

        # Acquire questions
        logging.getLogger(__name__).debug("Fetching questions; params: {}".format(params))
        questions_raw = self.client.make_request(opentdb["api_route"], params=params)["results"]
        for i in range(len(questions_raw)):
            el = questions_raw[i]
            question = discord.utils.escape_markdown(unquote(el["question"]))
            correct_answer = discord.utils.escape_markdown(unquote(el["correct_answer"]))
            info = {
                "difficulty": el["difficulty"],
                "category": el["category"],
            }
            incorrect_answers = [discord.utils.escape_markdown(unquote(ia)) for ia in el["incorrect_answers"]]
            self.questions.append(Question(question, correct_answer, incorrect_answers, index=i, info=info))

    def current_question_index(self):
        return self.current_question_i

    @classmethod
    def size(cls, **kwargs):
        """
        :return: Returns how many questions there are in the database under the given constraints. Returns None
        if the constraints are not supported (e.g. unknown category).
        """
        difficulty = Difficulty.ANY
        if "difficulty" in kwargs:
            difficulty = kwargs["difficulty"]
        cat = "any"
        if "category" in kwargs and kwargs["category"] is not None:
            cat = kwargs["category"]

        if cat == -1:
            cats = [el["id"] for el in opentdb["cat_mapping"] if el["id"] != -1]
        else:
            cats = [cat]
        r = 0
        client = restclient.Client(opentdb["base_url"])
        for cat in cats:
            params = {
                "category": str(cat),
                "encode": "url3986",
            }
            counts = client.make_request(opentdb["api_count_route"], params=params)["category_question_count"]
            if difficulty == Difficulty.ANY:
                key = "total_question_count"
            elif difficulty == Difficulty.EASY:
                key = "total_easy_question_count"
            elif difficulty == Difficulty.MEDIUM:
                key = "total_medium_question_count"
            elif difficulty == Difficulty.HARD:
                key = "total_medium_question_count"
            else:
                return None

            r += int(counts[key])
        return r

    @classmethod
    def info(cls, **kwargs):
        return "Question count: {}".format(cls.size(**kwargs))

    @staticmethod
    def category_name(catkey):
        """
        :return: Human-readable representation of the quiz category
        """
        if catkey is None:
            catkey = OpenTDBQuizAPI.category_key(opentdb["default_cat"])
        _, name = catkey.get(OpenTDBQuizAPI)
        return name

    @staticmethod
    def category_key(catarg):
        """
        :param catarg: Argument that was passed that identifies a
        :return: Opaque category identifier that can be used in initialization and for category_name.
        Returns None if catarg is an unknown category.
        """
        if catarg is None:
            catarg = opentdb["default_cat"]
        for mapping in opentdb["cat_mapping"]:
            for cat in mapping["names"]:
                if catarg.lower() == cat:
                    catkey = CategoryKey()
                    catkey.add_key(OpenTDBQuizAPI, mapping["id"], mapping["names"][0])
                    return catkey
        return None

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


class MetaQuizAPI(BaseQuizAPI):
    """
    Quiz API that combines all existing ones.
    """
    apis = [OpenTDBQuizAPI]

    def __init__(self, config, channel,
                 category=None, question_count=None, difficulty=Difficulty.EASY,
                 debug=False):
        """
        Pulls from all implemented quiz APIs.
        :param config: config dict
        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        logging.info("Quiz API: Meta")
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

        # Meta stuff
        self.spacesize = 0

        # Determine question space sizes, weights and question sequence
        sizes = {}
        apiclasses = []
        weights = []
        for el in self.apis:
            size = el.size(category=self.category, difficulty=self.difficulty)
            if size is not None:
                apiclasses.append(el)
                weights.append(size)
                sizes[el] = size
                self.spacesize += size

        question_seq = random.choices(apiclasses, weights=weights, k=self.question_count)
        question_counts = {el: 0 for el in apiclasses}
        for el in question_seq:
            question_counts[el] += 1

        apis = {el: el(self.config, self.channel, category=self.category, question_count=question_counts[el],
                       difficulty=self.difficulty, debug=self.debug) for el in apiclasses}

        # Build questions list
        for i in range(self.question_count):
            self.questions.append(apis[question_seq[i]].next_question())

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

    @staticmethod
    def category_key(catarg):
        """
        :param catarg: Argument that was passed that identifies a
        :return: Opaque category identifier that can be used in initialization and for category_name.
        Returns None if catarg is an unknown category.
        """
        for api in MetaQuizAPI.apis:
            r = api.category_key(catarg)
        return None

    @classmethod
    def size(cls, **kwargs):
        r = 0
        for api in cls.apis:
            size = api.size(**kwargs)
            if size is not None:
                r += size
        return r

    @classmethod
    def info(cls, **kwargs):
        return "Question count: {}".format(cls.size(**kwargs))

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


quizapis = {
    "opentdb": OpenTDBQuizAPI,
    "meta": MetaQuizAPI,
}
