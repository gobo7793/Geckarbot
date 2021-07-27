import logging
import asyncio
from urllib.parse import unquote, urlencode
from html import unescape
import random
import json
import re
from typing import Type

import aiohttp
import discord

from botutils import restclient

from plugins.quiz.controllers import QuizEnded
from plugins.quiz.base import BaseQuizAPI, BaseCategoryController, Difficulty, Question
from plugins.quiz.categories import DefaultCategory, CategoryController


class QuizAPIError(Exception):
    """
    Raised when quizapi.fetch() fails
    """
    pass


class InvalidCategory(Exception):
    pass


class OpenTDBQuizAPI(BaseQuizAPI):
    """
    Uses OpenTDB as a question resource
    """
    NAME = "opentdb"
    BASE_URL = "https://opentdb.com"
    TOKEN_ROUTE = "api_token.php"
    API_ROUTE = "api.php"
    API_COUNT_ROUTE = "api_count.php"
    CAT_MAP = {
        DefaultCategory.ALL: -1,
        DefaultCategory.MISC: 9,
        DefaultCategory.LITERATURE: 10,
        DefaultCategory.FILMTV: 11,
        DefaultCategory.MUSIC: 12,
        DefaultCategory.SCIENCE: 17,
        DefaultCategory.COMPUTER: 18,
        DefaultCategory.GAMES: 15,
        DefaultCategory.MYTHOLOGY: 20,
        DefaultCategory.HISTORY: 23,
        DefaultCategory.POLITICS: 24,
        DefaultCategory.ART: 25,
        DefaultCategory.ANIMALS: 27,
        DefaultCategory.GEOGRAPHY: 22,
        DefaultCategory.SPORT: 21,
        DefaultCategory.MATHEMATICS: 19,
        DefaultCategory.CELEBRITIES: 26,
        DefaultCategory.COMICS: 29,
    }

    """
    unused:
      Musical / Theatre (13)
      Boardgames (16)
      Vehicles (28)
      Gadgets (30)
      Anime / Manga (31)
      Cartoons (32)
      TV (14)
    """

    def __init__(self, channel, category, question_count, difficulty=Difficulty.EASY, debug=False):
        """
        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        logging.info("Quiz API: OpenTDB")
        self.debug = debug
        self.channel = channel
        self.difficulty = difficulty
        self.question_count = question_count

        self.client = restclient.Client(self.BASE_URL)
        self.current_question_i = -1
        self.is_running = True

        self.category = category
        self.questions = []
        self.token = None

    @classmethod
    def register_categories(cls, category_controller):
        for cat, catkey in cls.CAT_MAP.items():
            category_controller.register_category_support(cls, cat, catkey)

    async def get_token(self):
        if self.token is None:
            self.token = await self.client.request(self.TOKEN_ROUTE, params={"command": "request"})
            self.token = self.token["token"]

    async def fetch(self):
        await self.get_token()

        # Build request params
        params = {
            "token": self.token,
            "amount": self.question_count,
            "encode": "url3986",
            "type": "multiple",
        }
        if self.category > 0:
            params["category"] = self.category
        if self.difficulty != Difficulty.ANY:
            params["difficulty"] = self.difficulty.value

        # Fetch questions
        logging.getLogger(__name__).debug("Fetching questions; params: %s", str(params))
        questions_raw = await self.client.request(self.API_ROUTE, params=params)
        questions_raw = questions_raw["results"]
        for i in range(len(questions_raw)):
            el = questions_raw[i]
            question = discord.utils.escape_markdown(unquote(el["question"]))
            correct_answer = discord.utils.escape_markdown(unquote(el["correct_answer"]))
            info = {
                "difficulty": el["difficulty"],
                "category": el["category"],
            }
            incorrect_answers = [discord.utils.escape_markdown(unquote(ia)) for ia in el["incorrect_answers"]]
            self.questions.append(Question(self, question, correct_answer, incorrect_answers, index=i, info=info))

    def current_question_index(self):
        """
        :return: Index of the current question
        """
        return self.current_question_i

    @classmethod
    async def _fetch_cat_size(cls, client, cat, difficulty, result):
        params = {
            "category": cat,
            "encode": "url3986",
        }
        counts = await client.request(cls.API_COUNT_ROUTE, params=params)
        counts = counts["category_question_count"]
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

        result.append(int(counts[key]))

    @classmethod
    async def size(cls, **kwargs):
        """
        :return: Returns how many questions there are in the database under the given constraints. Returns None
            if the constraints are not supported (e.g. unknown category).
        """
        difficulty = kwargs["difficulty"] if "difficulty" in kwargs else Difficulty.ANY
        cat = kwargs["category"]
        if cat == -1:
            cats = [el for _, el in cls.CAT_MAP.items() if el != -1]
        else:
            cats = [cat]
        client = restclient.Client(cls.BASE_URL)

        tasks = []
        result = []
        for cat in cats:
            tasks.append(cls._fetch_cat_size(client, cat, difficulty, result))
        await asyncio.wait(tasks)
        return sum(result)

    @classmethod
    async def info(cls, **kwargs):
        return "Question count: {}".format(cls.size(**kwargs))

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


class Pastebin(BaseQuizAPI):
    """
    Uses a list of questions on Pastebin.
    """

    NAME = "pastebin"
    URL = "https://pastebin.com/raw/QRGzxxEy"

    def __init__(self, channel, category, question_count, difficulty=None, debug=False):
        self.logger = logging.getLogger(__name__)
        self.questions = None
        self.current_question_i = -1
        self.question_count = question_count
        self.channel = channel
        self.difficulty = difficulty
        self.debug = debug
        self.category = category

    @classmethod
    def register_categories(cls, category_controller):
        category_controller.register_category_support(cls, DefaultCategory.ALL, None)
        category_controller.register_category_support(cls, DefaultCategory.MISC, None)

    async def fetch(self):
        self.logger.debug("Pastebin QuizAPI: Fetching questions")
        async with aiohttp.ClientSession() as session:
            async with session.get(self.URL) as response:
                response = await response.text()
        response = json.loads(response)
        self.questions = random.choices(range(len(response)), k=self.question_count)
        for i in range(len(self.questions)):
            el = response[self.questions[i]]
            question = el["question"]
            correct = el["answer"]
            answers = []
            found = False
            for letter in ["A", "B", "C", "D"]:
                if letter == correct:
                    correct = el[letter]
                    found = True
                else:
                    answers.append(el[letter])
            assert found
            self.questions[i] = Question(self, question, correct, answers, index=i)

    def current_question_index(self):
        return self.current_question_i

    def current_question(self):
        return self.questions[self.current_question_i]

    def next_question(self):
        self.current_question_i += 1
        if self.current_question_i > len(self.questions) - 1:
            raise QuizEnded

        return self.questions[self.current_question_i]

    @classmethod
    async def size(cls, **kwargs):
        return 547

    async def info(self, **kwargs):
        return "Not impl yet"

    def __del__(self):
        pass


class Fragespiel(BaseQuizAPI):
    """
    Scrapes questions from fragespiel.com
    """
    NAME = "fragespiel"
    CATEGORIES = {
        DefaultCategory.ALL: ["1", "2", "3", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "17", "18",
                              "19", "20", "23", "24", "25", "26", "30", "31", "32", "33", "34", "35", "36", "37"],
        DefaultCategory.MISC: ["7"],
        DefaultCategory.LITERATURE: ["13"],
        DefaultCategory.FILMTV: ["34"],
        DefaultCategory.MUSIC: ["33"],

        # Chemie, Biologie, Astronomie, Physik, Wissenschaft, Medizin, Pflanzen
        DefaultCategory.SCIENCE: ["5", "6", "11", "12", "14", "23", "26"],
        DefaultCategory.COMPUTER: ["19"],
        DefaultCategory.TECH: ["37"],
        DefaultCategory.MYTHOLOGY: ["35"],
        DefaultCategory.HISTORY: ["3"],
        DefaultCategory.POLITICS: ["10"],

        # Kunst, Bauwerke
        DefaultCategory.ART: ["30", "31"],
        DefaultCategory.ANIMALS: ["24"],
        DefaultCategory.GEOGRAPHY: ["8"],
        DefaultCategory.SPORT: ["20"],
        DefaultCategory.MATHEMATICS: ["36"],
        DefaultCategory.FASHION: ["2"],
        DefaultCategory.RELIGION: ["17"],
        DefaultCategory.ECONOMICS: ["18"],
        DefaultCategory.FOOD: ["25"],
        DefaultCategory.PHILOSOPHY: ["32"],
    }

    """
    unused:
        "4": "Erotik",
        "15": "Österreich"
        "16": "Deutschland"
        "39": "DDR"
    """

    URL = "https://www.fragespiel.com/quiz/training.html"

    def __init__(self, channel, category, question_count, difficulty=None, debug=False):
        self.logger = logging.getLogger(__name__)
        self.channel = channel
        self.categories = category
        self.question_count = question_count
        self.difficulty = difficulty
        self.debug = debug
        self.questions = []
        self.current_question_i = -1

        self.aiosession = aiohttp.ClientSession()

    @classmethod
    def register_categories(cls, category_controller):
        for cat, key in cls.CATEGORIES.items():
            category_controller.register_category_support(cls, cat, key)

    async def fetch(self):
        done = 0
        buffer = None
        answer_keys = ("a", "b", "c", "d")

        # Build payload
        payload = [("play", "true")]

        for cat in self.categories:
            payload.append(("kat[]", cat))

        payload += [
            ("anzahl", 10),
            ("bt_start", "Quiz starten"),
        ]
        payload = urlencode(payload)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # Fetch a new set of questions (if necessary), check for dupes and fill self.questions
        strikes = 0
        while done < self.question_count:
            if strikes == self.question_count * 4:
                raise QuizAPIError("Unable to fetch enough questions")

            # Fetch
            if not buffer:
                async with self.aiosession.post(self.URL, data=payload, headers=headers) as response:
                    response = await response.text()
                buffer = self.scrape_questions(response)
                continue

            # Check for dupe and 4 answers
            candidate = buffer.pop()
            violation = False

            for key in answer_keys:
                if not candidate[key][0]:
                    violation = True
                    break
            if violation:
                strikes += 1
                continue

            for question in self.questions:
                if candidate["title"] == question.question:
                    violation = True
                    break
            if violation:
                strikes += 1
                continue

            # Build question
            inc = []
            for el in answer_keys:
                if el != candidate["answer"]:
                    inc.append(candidate[el][0])
            question = Question(self, candidate["title"], candidate[candidate["answer"]][0], inc, index=done)
            self.questions.append(question)
            done += 1
        await self.aiosession.close()

    @staticmethod
    def scrape_questions(html):
        """
        Scrapes questions from the web page.

        :param html: web page html
        :return: List of question dicts
        :raises QuizAPIError: Raised if a parsing error occured
        """
        p = re.compile(r"'json'\s:\s'([^']*)'")
        r = p.search(html)
        if r is None:
            raise QuizAPIError("No questions found in html")
        try:
            questions = json.loads(r.groups()[0])["questions"]
        except Exception as e:
            logging.getLogger(__name__).error("Error on parsing fragespiel questions json:\n%s", r.groups()[0])
            raise QuizAPIError("Unexpected parsing error") from e

        # Unescape
        for question in questions:
            question["title"] = unescape(question["title"])
            for key in ("a", "b", "c", "d"):
                question[key][0] = unescape(question[key][0])
        return questions

    def current_question(self):
        return self.questions[self.current_question_i]

    def next_question(self):
        if self.current_question_i >= len(self.questions) - 1:
            raise QuizEnded
        self.current_question_i += 1
        return self.current_question()

    def current_question_index(self):
        return self.current_question_i

    @classmethod
    async def size(cls,  **kwargs):
        return None

    async def info(self, **kwargs):
        pass

    def __del__(self):
        pass


class MockCategoryController(BaseCategoryController):
    """
    Collects category registrations from quiz APIs that Meta controls.
    """
    def __init__(self):
        self.categories = {}

    def register_category_support(self, apiclass: Type[BaseQuizAPI], category: DefaultCategory, catkey):
        if category in self.categories:
            self.categories[category][apiclass] = catkey
        else:
            self.categories[category] = {
                apiclass: catkey
            }


class MetaQuizAPI(BaseQuizAPI):
    """
    Quiz API that combines all existing ones.
    """
    NAME = "meta"
    apis = [OpenTDBQuizAPI, Pastebin, Fragespiel]

    def __init__(self, channel, category, question_count, difficulty=Difficulty.EASY, debug=False):
        """
        Pulls from all implemented quiz APIs.

        :param channel: channel ID that this quiz was requested in
        :param category: Question topic / category. If None, it is chosen according to channel default mapping.
        :param question_count: Amount of questions to be asked, None for default
        :param difficulty: Difficulty enum ref that determines the difficulty of the questions
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info("Quiz API: Meta")

        self.debug = debug
        self.channel = channel
        self.difficulty = difficulty
        self.question_count = question_count

        self.client = restclient.Client(OpenTDBQuizAPI.BASE_URL)
        self.current_question_i = -1

        self.category = category
        self.questions = []
        self.is_running = True

        # Meta stuff
        self.spacesize = 0

    @classmethod
    def register_categories(cls, category_controller):
        mock_controller = MockCategoryController()
        for quizapi in cls.apis:
            quizapi.register_categories(mock_controller)
        for category, catkey in mock_controller.categories.items():
            category_controller.register_category_support(cls, category, catkey)

    async def fetch(self):
        # Determine question space sizes, weights and question sequence
        sizes = {}
        apiclasses = []
        weights = []
        to_guess = []
        for api, catkey in self.category.items():
            if catkey is None:
                continue
            size = await api.size(category=catkey, difficulty=self.difficulty)
            if size is None:
                to_guess.append(api)
            else:
                apiclasses.append(api)
                weights.append(size)
                sizes[api] = size
                self.spacesize += size

        if weights:
            average = sum(weights) / len(weights)
        else:
            average = 1
        for api in to_guess:
            apiclasses.append(api)
            weights.append(average)

        question_seq = random.choices(apiclasses, weights=weights, k=self.question_count)
        question_counts = {el: 0 for el in apiclasses}
        for el in question_seq:
            question_counts[el] += 1

        self.logger.debug("Meta Quiz API; fetching from quiz APIs:")
        apis = {}
        for api in apiclasses:
            self.logger.debug("%s from %s", question_counts[api], api)
            apis[api] = api(self.channel, self.category[api], question_counts[api],
                            difficulty=self.difficulty, debug=self.debug)
            await apis[api].fetch()

        # Build questions list
        for i in range(self.question_count):
            question = apis[question_seq[i]].next_question()
            question.index = i
            self.questions.append(question)

    def current_question_index(self):
        """
        :return: Index of the current question
        """
        return self.current_question_i

    @classmethod
    async def size(cls, **kwargs):
        r = 0
        for api in cls.apis:
            # Build QuizAPI-specific kwargs
            args = kwargs.copy()
            if "category" in args:
                args["category"] = args["category"][api]

            size = await api.size(**args)
            if size is not None:
                r += size
        return r

    @classmethod
    async def info(cls, **kwargs):
        return "Question count: {}".format(await cls.size(**kwargs))

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
    "pastebin": Pastebin,
    "fragespiel": Fragespiel
}
