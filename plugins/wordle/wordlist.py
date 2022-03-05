import random
import re
from string import ascii_lowercase
from enum import Enum
from typing import List

import aiohttp


TO_ADD = [
    "gecki"
]


class Parsers(Enum):
    POWERLANGUAGE = "powerlanguage"


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


async def fetch_powerlanguage_impl(url: str) -> WordList:
    """
    Builds a WordList from a default wordle implementation url.

    :param url: wordle url
    :return: built WordList
    :raises ValueError: If the script js was not found on the main page
    """
    session = aiohttp.ClientSession()

    # find script file
    p = re.compile(r"<script\s*src=\"([^>]+)\">")
    async with session.get(url) as response:
        response = await response.text()

    scriptfile = p.search(response)
    if scriptfile is None:
        raise ValueError("Wordle page parse error: main.js not found")
    scriptfile = scriptfile.groups()[0]

    # parse list strings out of script file
    p = re.compile(r"(\[(\"[a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z]\",?)+])")
    if url.endswith("/"):
        url = url[:-1]
    async with session.get("{}/{}".format(url, scriptfile)) as response:
        response = await response.text(encoding="utf8")
    lists = p.findall(response)

    # parse words out of list strings
    p = re.compile(r"\"([a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z][a-zA-Z])\"")
    for i in range(len(lists)):
        wlist = lists[i][0]
        lists[i] = p.findall(wlist)
    assert len(lists) == 2

    # build WordList
    solutions = normalize_wlist(lists[0])
    complement = normalize_wlist(lists[1])
    del lists
    if len(solutions) > len(complement):
        solutions, complement = complement, solutions

    return WordList(url, Parsers.POWERLANGUAGE, tuple(solutions), tuple(complement))
