from abc import ABC, abstractmethod


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

    @abstractmethod
    def size(self, **kwargs):
        """
        Calculates the question space size for the given constraints (such as category and difficulty).
        :return: int
        """
        pass

    @abstractmethod
    def info(self, **kwargs):
        """
        :param kwargs:
        :return: Returns an info string under the given constraints.
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
