from enum import Enum
from typing import List, Callable, Union

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
        is expected to be callback(question, question_queue) with `question` being this Question object
        and `question_queue` being the list of questions that are planned to be posed after this.
        The answer(s) that was given will be stored in this object's `answer` attribute.
        The callback function is expected to return a new question queue.
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
    def __init__(self, bot, target_user: User, questions: List[Question]):
        self.bot = bot
        self.user = target_user
        self.question_queue = questions
        self.current_question_index = -1
        self.question_history = []
        self.dm_registration = None

    def set_callback(self, callback: Callable):
        """
        Sets a callback for all questions that do not have one.
        :param callback: Callback function that is called after each question was answered. Signature
        is expected to be callback(question, question_queue) with `question` being the Question object
        and `question_queue` being the list of questions that are planned to be posed after each question.
        The answer(s) that was given will be stored in the question object's `answer` attribute.
        The callback function is expected to return a new question queue.
        """
        for el in self.question_queue:
            if el.callback is None:
                el.callback = callback

    async def dm_callback(self, reg, msg):
        pass

    async def interrogate(self) -> List[Question]:
        """
        Starts the questionnaire process in the user's DM. If the DM channel is blocked, the appropriate exception
        is raised (see DM subsys).
        :return: List of questions that were posed. The question objects contain the given answers.
        """
        # Acquire DM channel
        self.dm_registration = self.bot.dm_listener.register(self.user, self.dm_callback, blocking=True)

        # Pose questions
        question = None
        while True:
            question = self.get_next_question(question)
            if question is None:
                break

            # Pose question and release lock
            await self.user.send()

        # Done
        self.dm_registration.deregister()
        return self.question_history

    def get_next_question(self, last_question) -> Union[Question, None]:
        """
        Does the question and callback handling.
        :return: Question object, None if there is no next question.
        """
        if last_question is not None and last_question.callback is not None:
            self.question_queue = last_question.callback(last_question, self.question_queue)
        self.current_question_index += 1
        if len(self.question_queue) > 0:
            r = self.question_queue.pop(0)
            self.question_history.append(r)
            return r
        else:
            return None
