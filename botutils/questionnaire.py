from enum import Enum
from typing import List, Callable

from discord import User


class QuestionType(Enum):
    TEXT = 0
    SINGLECHOICE = 1
    MULTIPLECHOICE = 2


class Question:
    def __init__(self, question: str,
                 qtype: QuestionType,
                 answers: List[str] = None,
                 callback: Callable = None,
                 data=None):
        """
        :param question: Question to be posed
        :param qtype: Question type
        :param answers: Possible answers
        :param callback: Callback function that is called after this question was answered. Signature
        is expected to be callback(question) with `question` being this Question object.
        The answer(s) that was given will be stored in this object's `answer` attribute.
        :param data: Opaque object that is set as this object's `data` object. Useful for callback.
        """
        self.question = question
        self.type = qtype
        self.answers = answers
        self.callback = callback
        self.data = data

        self.answer = None

        if answers is None and qtype != QuestionType.TEXT:
            raise RuntimeError("missing answers")


class Questionnaire:
    def __init__(self, target_user: User, questions: List[Question]):
        self.questions = questions

    def set_callback(self, callback: Callable):
        """
        Sets a callback for all questions that do not have one.
        :param callback: Callback function that is called after a question was answered. Signature
        is expected to be callback(question) with `question` being the answered question object.
        The answer(s) that was given will be stored in the question object's `answer` attribute.
        :return:
        """
        for el in self.questions:
            if el.callback is None:
                el.callback = callback

    def interrogate(self) -> List[Question]:
        """
        Starts the questionnaire process in the user's DM. If the DM channel is blocked, the appropriate exception
        is raised (see DM subsys).
        :return: List of questions that were posed. The question objects contain the given answers.
        """
        return self.questions
