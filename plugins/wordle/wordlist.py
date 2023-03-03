import abc
import json
import random
import re
from datetime import date
from enum import Enum
from string import ascii_lowercase
from typing import List, Tuple, Any

import aiohttp

TO_ADD = [
    "gecki"
]


class Parsers(Enum):
    NYTIMES = "nytimes"

    @classmethod
    def get(cls, parser):
        if parser == cls.NYTIMES.value:
            return Nytimes
        raise KeyError


class WordList:
    """
    A word list consists of two lists: The solutions and the complement. They are disjunctive. Together,
    they form the entire word space.
    """
    def __init__(self, url: str, parser: Parsers, solutions: tuple, complement: tuple):
        """

        :param url: URL this was parsed from
        :param parser: parser that was used
        :param solutions: tuple of words that can be a solution
        :param complement: tuple of the remaining words
        """
        self.url = url
        self.parser = parser
        self.solutions = solutions
        self.complement = complement
        self.alphabet = ascii_lowercase

        self._wordlist_cache = None

    def __str__(self):
        s = len(self.solutions)
        p = self.parser.value
        c = len(self.complement)
        return "<WordList: url: {}; parser: {}; solutions: {}; complement: {}>".format(self.url, p, s, c)

    def __contains__(self, item):
        return item in self.solutions or item in self.complement

    @property
    def words(self):
        """
        :return: List of all words; cached
        """
        if self._wordlist_cache is None:
            self._wordlist_cache = list(self.complement + self.solutions)
        return self._wordlist_cache

    def invalidate_cache(self):
        self._wordlist_cache = None

    def serialize(self):
        """
        Serializes the word list.

        :return: dict that can be fed into `WordList.deserialize()`.
        """
        return {
            "url": self.url,
            "parser": self.parser.value,
            "solutions": list(self.solutions),
            "complement": list(self.complement),
        }

    @classmethod
    def deserialize(cls, d):
        return cls(d["url"], Parsers(d["parser"]), tuple(d["solutions"] + TO_ADD), tuple(d["complement"]))

    def random_solution(self):
        return random.choice(self.solutions)


class Parser(abc.ABC):
    @classmethod
    @abc.abstractmethod
    async def fetch(cls, url: str) -> WordList:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    async def fetch_daily(cls, url: str) -> Tuple[str, Any]:
        """
        Fetches a daily word.

        :param url: url to fetch from
        :return: tuple (daily word, further info (e.g. epoch index))
        """
        raise NotImplementedError


class Nytimes(Parser):
    EPOCH = date(2021, 6, 19)
    DAILY_URL = "https://www.nytimes.com/svc/wordle/v2/{}-{:02d}-{:02d}.json"
    DAILY_INDEX = "days_since_launch"
    DAILY_SOLUTION = "solution"

    @staticmethod
    async def fetch_lists(url: str) -> Tuple[Tuple, Tuple]:
        """
        fetches solutions and complement lists

        :param url: url
        :return: solutions, complement
        """

        session = aiohttp.ClientSession()

        # find script file
        p = re.compile(r"<script.*?src=\"([^>]+wordle[^>]*\.js)\">")
        async with session.get(url) as response:
            response = await response.text()

        scriptfile = p.search(response)
        if scriptfile is None:
            raise ValueError("Wordle page parse error: wordle.js not found")
        scriptfile = scriptfile.groups()[0]
        print("scriptfile: {}".format(scriptfile))

        # parse list strings out of script file
        p = re.compile(r"(\[(\"[a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z]\",?)+])")
        if url.endswith("index.html"):
            url = url[:-len("index.html")]
        if url.endswith("/"):
            url = url[:-1]
        async with session.get(scriptfile) as response:
            response = await response.text(encoding="utf8")
        lists = p.findall(response)

        # parse words out of list strings
        p = re.compile(r"\"([a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z])\"")
        for i in range(len(lists)):
            wlist = lists[i][0]
            lists[i] = p.findall(wlist)

        # Used to be 2 lists (complement, solutions); was changed to single list (parsed below) early 2023
        assert len(lists) == 1
        wlist = lists[0]

        # build word lists; assumed format: ["abc", "abe", "bce", ..., "sol1", "sol2", "sol3"]
        complement = []
        solutions = []
        last_word = None
        for word in wlist:
            if last_word is None:
                complement.append(word)
            else:
                if solutions:
                    # wrap; we are in solutions territory
                    solutions.append(word)
                elif word < last_word:
                    # lexical ordering; we are at the complement-solutions-border
                    solutions.append(word)
                else:
                    complement.append(word)
            last_word = word
        solutions = normalize_wlist(solutions)
        complement = normalize_wlist(complement)
        return solutions, complement

    @classmethod
    async def fetch(cls, url: str) -> WordList:
        """
        Builds a WordList from a default wordle implementation url.

        :param url: wordle url
        :return: built WordList
        :raises ValueError: If the script js was not found on the main page
        """
        solutions, complement = await cls.fetch_lists(url)
        return WordList(url, Parsers.NYTIMES, solutions, complement)

    @classmethod
    async def fetch_daily(cls, url: str) -> Tuple[str, Any]:
        session = aiohttp.ClientSession()

        td = date.today()
        async with session.get(cls.DAILY_URL.format(td.year, td.month, td.day)) as response:
            response = await response.text()
        print("got {}".format(response))
        response = json.loads(response)
        return response[cls.DAILY_SOLUTION], response[cls.DAILY_INDEX]


def normalize_wlist(wl: List[str]) -> tuple:
    """
    Takes a list of words and normalizes it into a lowercase tuple of itself.
    Also asserts word list of 5.

    :param wl: list to normalize
    :return: tuple of words
    """
    for el in sorted(wl):
        assert len(el) == 5
    return tuple(wl)

