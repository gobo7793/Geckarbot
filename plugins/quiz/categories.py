from enum import Enum
from typing import Union, Sequence, Type, Any

from plugins.quiz.base import BaseQuizAPI, BaseCategoryController


class CategoryKey:
    pass


class DefaultCategory(Enum):
    """
    Default categories that most APIs implement
    (not used yet)
    """
    ALL = ("Any", ["any", "all"])
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
    FASHION = ("Fashion", ["fashion"])
    RELIGION = ("Religion", ["religion"])
    ECONOMICS = ("Economics", ["economics"])
    FOOD = ("Food", ["food"])
    PHILOSOPHY = ("Philosophy", ["philosophy", "philo"])


class Category:
    """
    Default categories are built into this structure at runtime.
    """
    def __init__(self, name: str, args: Sequence[str]):
        self.name = name
        self.args = args  # argument strings that this category is identified by
        self.supporters = {}  # dict of the form {QuizAPI class: category key} with category key being an opaque object

    def register_support(self, apiclass: Type[BaseQuizAPI], catkey: object):
        """
        Registers an apiclass that supports this category.

        :param apiclass: QuizAPI class
        :param catkey: Opaque object
        """
        self.supporters[apiclass] = catkey


class CategoryController(BaseCategoryController):
    """
    Controller for categories. Quiz APIs register categories they support, argument parser requests category keys from
    here.
    """
    def __init__(self):
        self.categories = {}
        for el in DefaultCategory:
            name, args = el.value
            self.categories[el] = Category(name, args)

    def register_category_support(self, apiclass: Type[BaseQuizAPI], category: DefaultCategory, catkey: Any):
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

    def get_name_by_category_key(self, quizapi: Type[BaseQuizAPI], catkey: Any) -> str:
        """
        :param quizapi: QuizAPI class
        :param catkey: category key
        :return: Category name that correspons to the category key
        :raises RuntimeError: If category that corresponds to catkey was not found
        """
        for _, category in self.categories.items():
            if quizapi in category.supporters and category.supporters[quizapi] == catkey:
                return category.name
        raise RuntimeError("Category {} not found".format(catkey))

    def get_supporters(self, category: DefaultCategory) -> list:
        return list(self.categories[category].supporters.keys())

    def get_category_key(self, quizapi: Type[BaseQuizAPI], category: DefaultCategory) -> Any:
        """
        Returns the category key that a quizapi registered its support with.

        :param quizapi:
        :param category: DefaultCategory object that corresponds to a supported category
        :return: Opaque object that is used on quiz api init
        """
        assert quizapi in self.categories[category].supporters, "{} does not support {}".format(quizapi, category)
        return self.categories[category].supporters[quizapi]
