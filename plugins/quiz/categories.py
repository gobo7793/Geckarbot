from enum import Enum
from typing import Union, Sequence

from plugins.quiz.base import BaseQuizAPI


class CategoryKey:
    pass


class DefaultCategory(Enum):
    """
    Default categories that most APIs implement
    (not used yet)
    """
    ALL = ("Any", ["any"])
    MISC = ("Misc", ["misc", "general"])
    LITERATURE = ("Literature", ["literature", "books"])
    FILMTV = ("Film and TV", ["film", "movie", "movies", "tv", "television"])
    MUSIC = ("Music", ["music"])
    SCIENCE = ("Science", ["science", "nature"])
    COMPUTER = ("Computer", ["computer"])
    GAMES = ("Games", ["games"])
    TECH = ("Tech", ["tech"])
    MYTHOLOGY = ("Mythology", ["mythology"])
    HISTORY = ("History", ["history"])
    POLITICS = ("Politics", ["politics"])
    ART = ("Art", ["art"])
    ANIMALS = ("Animals", ["animals"])
    GEOGRAPHY = ("Geography", ["geography", "geo"])
    SPORT = ("Sport", ["sport", "sports"])
    MATHEMATICS = ("Mathematics", ["mathematics", "math"])
    CELEBRITIES = ("Celebrities", ["celebrities"])
    COMICS = ("Comics", ["comics"])


class Category:
    def __init__(self, name: str, args: Sequence[str]):
        self.name = name
        self.args = args  # argument strings that this category is identified by
        self.supporters = {}  # dict of the form {QuizAPI class: category key} with category key being an opaque object

    def register_support(self, apiclass: BaseQuizAPI, catkey: object):
        """
        Registers an apiclass that supports this category.

        :param apiclass: QuizAPI class
        :param catkey: Opaque object
        """
        self.supporters[apiclass] = catkey


class CategoryController:
    def __init__(self, quizapis: Sequence[BaseQuizAPI]):
        self.categories = {}
        for el in DefaultCategory:
            name, args = el.value
            self.categories[el] = Category(name, args)

        # init quizapis
        for el in quizapis:
            el.register_categories(self)

    def register_category_support(self, apiclass: BaseQuizAPI, category: DefaultCategory, catkey):
        """
        Registers the support of a specific default category for a quiz api class.

        :param apiclass: QuizAPI class reference
        :param category: DefaultCategory that is supported
        :param catkey: Opaque category key that is handed back on api init
        """
        assert category in DefaultCategory
        self.categories[category].register_support(apiclass, catkey)

    def get_cat_by_arg(self, arg: str) -> Union[DefaultCategory, None]:
        """
        Returns a DefaultCategory that corresponds to arg, None if there is none.

        :param arg: argument that was passed in a command
        :return: DefaultCategory object if cat exists; None otherwise
        """
        for cat in DefaultCategory:
            if arg in self.categories[cat].args:
                return cat
        return None

    def get_supporters(self, category: DefaultCategory) -> list:
        return list(self.categories[category].supporters.keys())

    def get_category_key(self, quizapi: BaseQuizAPI, category: DefaultCategory):
        """
        Returns the category key that a quizapi registered its support with.

        :param quizapi:
        :param category: DefaultCategory object that corresponds to a supported category
        :return: Opaque object that is used on quiz api init
        """
        assert quizapi in self.categories[category].supporters, "{} does not support {}".format(quizapi, category)
        return self.categories[category].supporters[quizapi]
