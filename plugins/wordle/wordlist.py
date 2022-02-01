from enum import Enum
import aiohttp
import re


class Parsers(Enum):
    POWERLANGUAGE = "powerlanguage"


class WordList:
    """
    A word list consists of two lists: The solutions and the complement. They are disjunctive. Together,
    they form the entire word space.
    """
    def __init__(self, url: str, parser: Parsers, solutions: set, complement: set):
        """

        :param url: URL this was parsed from
        :param parser: parser that was used
        :param solutions: set of words that can be a solution
        :param complement: the remaining set of words
        """
        self.url = url
        self.parser = parser
        self.solutions = solutions
        self.complement = complement

    def __str__(self):
        s = len(self.solutions)
        p = self.parser.value
        c = len(self.complement)
        return "<WordList: url: {}; parser: {}; solutions: {}; complement: {}>".format(self.url, p, s, c)

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
        return cls(d["url"], Parsers(d["parser"]), set(d["solutions"]), set(d["complement"]))


def normalize_wlist(wl) -> set:
    """
    Takes a list of words and normalizes it into a lowercase set of itself.
    Also asserts word list of 5.

    :param wl: list to normalize
    :return: set
    """
    r = set()
    for el in sorted(wl):
        assert(len(el) == 5)
        r.add(el.lower())
    return r


async def fetch_powerlanguage_impl(url: str) -> WordList:
    """
    Builds a WordList from a default wordle implementation url.

    :param url: wordle url
    :return: built WordList
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
    assert(len(lists) == 2)

    # build WordList
    solutions = normalize_wlist(lists[0])
    complement = normalize_wlist(lists[1])
    del lists
    if len(solutions) > len(complement):
        t = solutions
        solutions = complement
        complement = t

    return WordList(url, Parsers.POWERLANGUAGE, solutions, complement)
