import asyncio
import logging
from enum import Enum
from typing import List, Callable, Union

from discord import User, Message

from data import Lang
from botutils.stringutils import paginate, format_andlist as ellist
from botutils.utils import execute_anything, add_reaction

baselang = {
    "intro": "This is a questionnaire. I will ask questions and you may answer them.",
    "intro_howto_cancel": "To cancel, type `cancel` at any time. This will throw away any progress we made and your"
                          "answers will not be recorded.",
    "and": "and",
    "or": "or",
    "answer_cancel": "cancel",
    "answer_mc_done": "done",
    "answer_list_mc": "The possible answers are: {}\n"
                      "This is a multiple choice question, so you may choose as many as you want.\n"
                      "Please submit your answers one by one. When you are done, type `done`.",
    "answer_list_sc": "The possible answers are: {}\n"
                      "Please choose one out of these.",
    "no_answers": "Please submit an answer first.",

    "result_rejected": "Invalid answer.",

    "state_cancelled": "Cancelled.",
    "state_done": "Done! The questionnaire is over. Thank you very much."
}


def get_lang(lang_dict: dict, key: str) -> str:
    """
    Returns a lang string; handles fallbck to default lang

    :param lang_dict: lang dict to use
    :param key: lang key
    :return: lang string
    """
    r = lang_dict.get(key, baselang[key])
    if r is None:
        r = ""
    return r


class Cancelled(Exception):
    """
    Raised when user has cancelled the questionnaire
    """


class QuestionType(Enum):
    """
    Type of question
    """
    TEXT = 0
    SINGLECHOICE = 1
    MULTIPLECHOICE = 2


class Result(Enum):
    """
    Result of a question
    """
    DONE = 0  # question is done (accepted final answer)
    ACCEPTED = 1  # accepted answer, but not done yet (used in multiple choice)
    REJECTED = 2  # invalid answer
    EMPTY = 3  # done but no real answers submitted
    CANCELLED = 4  # questionnaire was cancelled


class State(Enum):
    """
    State for statemachine
    """
    INIT = 0
    QUESTION = 1
    ANSWER = 2
    DONE = 3


class Question:
    """
    Represents a question.
    """
    def __init__(self, question: str,
                 qtype: QuestionType,
                 answers: List[str] = None,
                 callback: Callable = None,
                 data=None,
                 lang: dict = None,
                 allow_empty: bool = False):
        """
        :param question: Question to be posed
        :param qtype: Question type
        :param answers: Possible answers
        :param callback: Callback function that is called after this question was answered. Signature
            is expected to be `callback(question, question_queue)` with `question` being this Question object
            and `question_queue` being the list of questions that are planned to be posed after this.
            The answer(s) that were given will be stored in this object's `answer` attribute.
            The callback function is expected to return a new question queue.
        :param data: Opaque object that is set as this object's `data` object. Useful for callback.
        :param lang: Custom lang dict with the following keys:
            "and": "and" string that is used when formatting multiple choice answers.
            "or": "or" string that is used when formatting single choice answers.
            "answer_cancel": Answer that can be used at any point in the questionnaire to cancel it.
            "answer_mc_done": Answer that is used to finish multiple choice answers. Usually something like "done".
            "answer_list_mc": 1-spot format string that takes the list of possible answers in multiple choice questions.
            Used to explain how to answer a multiple choice question.
            "answer_list_sc": 1-spot format string that takes the list of possible answers in single choice questions.
            Used to explain how to answer a single choice question.
        :param allow_empty: If set to True, allows empty answers list in multiple-choice type questions.
        :raises RuntimeError: No answers were given but question type is not `QuestionType.TEXT`
        """
        self.logger = logging.getLogger(__name__)
        self.question = question
        self.type = qtype
        self._answers = answers
        self.callback = callback
        self.data = data
        self.lang = lang if lang is not None else {}
        self.allow_empty = allow_empty

        self.answer = None
        self.question_msg = None
        self.answer_msg = None

        if not answers and qtype != QuestionType.TEXT:
            raise RuntimeError("missing answers")

    async def pose(self, user):
        """
        Sends the question and necessary info (such as the set of allowed answers).
        :param user: User to send the question to
        """
        msg = [self.question]
        if self.type == QuestionType.MULTIPLECHOICE:
            answers = ellist(self._answers, ands=get_lang(self.lang, "and"), emptylist="PANIC PANIC BEEEDOOO")
            msg.append(get_lang(self.lang, "answer_list_mc").format(answers))
        elif self.type == QuestionType.SINGLECHOICE:
            answers = ellist(self._answers, ands=get_lang(self.lang, "or"), emptylist="PANIC PANIC BEEEDOOO")
            msg.append(get_lang(self.lang, "answer_list_sc").format(answers))

        for msg in paginate(msg):
            if msg:
                self.question_msg = await user.send(msg)

    def handle_answer(self, answer_msg: Message) -> Union[Result, None]:
        """
        Handles an answer according to the question type.
        :param answer_msg: submitted answer message
        :return: The resulting new State
        """
        self.logger.debug("Handling answer %s on %s", answer_msg.content, str(self))
        if answer_msg.content.lower() == self.lang.get("answer_cancel", baselang["answer_cancel"]):
            return Result.CANCELLED

        self.answer_msg = answer_msg
        answer = answer_msg.content

        if self.type == QuestionType.TEXT:
            self.answer = answer
            return Result.DONE

        if self.type == QuestionType.SINGLECHOICE:
            if answer in self._answers:
                self.answer = answer
                return Result.DONE
            return Result.REJECTED

        if self.type == QuestionType.MULTIPLECHOICE:
            if answer == self.lang.get("answer_mc_done", baselang["answer_mc_done"]):
                if not self.allow_empty and not self.answer:
                    return Result.EMPTY
                return Result.DONE
            print("searching {} in {}".format(answer, self._answers))
            if answer in self._answers:
                # Create or append to answer list
                if self.answer is not None:
                    if answer not in self.answer:
                        self.answer.append(answer)
                else:
                    self.answer = [answer]
                return Result.ACCEPTED
            return Result.REJECTED

        return None

    def __str__(self):
        return "<questionnaire.Question object; question: {}>".format(self.question)

    def __repr__(self):
        return str(self)


class Questionnaire:
    """
    Questionnaire to interrogate a user via DM. Supports multiple variants of question types.
    """
    def __init__(self, bot, target_user: User, questions: List[Question], name: str,
                 kill_coro=None, lang: dict = None):
        """
        :param bot: bot reference
        :param target_user: user that is to be DM'ed
        :param questions: list of Question objects that are to be posed
        :param name: String that identifies this questionnaire (e.g. command name)
        :param kill_coro: DM registration kill callback; called when the DM registration is killed externally.
        If this happens, this Questionnaire won't do any cleanup work.
        :param lang: Custom lang dict with the following keys:
        "intro": String that is sent as an introductory message before any question is posed. Use this to explain
        what is going to happen in the questionnaire and how it is used.
        "intro_howto_cancel": Second message that is sent. Usually used to explain how the questionnaire is cancelled.
        "no_answers": Used in multiple choice questions to indicate that the "done" message cannot be the first.
        "result_rejected": Questionnaire response when the submitted answer is invalid.
        "state_cancelled": Response that is used when the questionnaire is cancelled.
        "state_done": Reponse that is used when the questionnaire is done.
        """
        self.bot = bot
        self.user = target_user
        self.name = name
        self.question_queue = questions
        self.current_question_index = -1
        self.current_question = None
        self.question_history = []
        self.kill_coro = kill_coro
        self.dm_registration = None
        self.state = State.INIT
        self.lang = lang if lang is not None else {}

        self.question_answered_event = asyncio.Event()
        self.logger = logging.getLogger(__name__)

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
        """
        Handler for incoming DMs

        :param reg: DM Registration
        :param msg: Message
        """
        if not self.state == State.ANSWER:
            await add_reaction(msg, Lang.CMDERROR)
            return

        result = self.current_question.handle_answer(msg)
        if result == Result.CANCELLED:
            self.state = State.DONE
            self.teardown()
            await self.user.send(get_lang(self.lang, "state_cancelled"))

        elif result == Result.DONE:
            self.question_answered_event.set()

        elif result == Result.ACCEPTED:
            await add_reaction(msg, Lang.CMDSUCCESS)

        elif result == Result.EMPTY:
            await add_reaction(msg, Lang.CMDERROR)
            await self.user.send(get_lang(self.lang, "no_answers"))

        elif result == Result.REJECTED:
            await add_reaction(msg, Lang.CMDERROR)
            await self.user.send(get_lang(self.lang, "result_rejected"))

    async def interrogate(self) -> Union[List[Question], None]:
        """
        Starts the questionnaire process in the user's DM. If the DM channel is blocked, the appropriate exception
        is raised (see DM subsys).
        :return: List of questions that were posed. The question objects contain the given answers. None if the
        questionnaire was cancelled.
        :raises Cancelled: questionnaire was cancelled by the user
        """
        # Setup
        self.dm_registration = self.bot.dm_listener.register(self.user, self.dm_callback, self.name,
                                                             kill_coro=self.kill_coro, blocking=True)
        self.logger.debug("Interrogating %s", str(self.user))

        # Intro
        msg = [
            self.lang.get("intro", baselang["intro"]),
            self.lang.get("intro_howto_cancel", baselang["intro_howto_cancel"])
        ]
        for msg in paginate(msg):
            if msg.strip():
                await self.user.send(msg)
            else:
                self.logger.warning("Questionnaire here; please fix empty returns in paginate thx")

        # Pose questions
        while True:
            self.state = State.QUESTION
            self.current_question = await self.get_next_question(self.current_question)
            self.logger.debug("Next question: %s", str(self.current_question))
            if self.current_question is None:
                self.state = State.DONE
                break

            # Pose question
            self.logger.debug("Posing question %i: %s", self.current_question_index,
                              str(self.current_question.question))
            self.state = State.ANSWER
            self.question_answered_event.clear()
            await self.current_question.pose(self.user)
            await self.question_answered_event.wait()

            if self.state == State.DONE:
                # We were cancelled; assuming self.teardown() was already called
                raise Cancelled()

        # Done
        msg = get_lang(self.lang, "state_done")
        if msg:
            await self.user.send(msg)
        self.teardown()
        return self.question_history

    async def get_next_question(self, last_question) -> Union[Question, None]:
        """
        Does the question and callback handling.
        :return: Question object, None if there is no next question.
        """
        if last_question is not None and last_question.callback is not None:
            self.question_queue = await execute_anything(last_question.callback, last_question, self.question_queue)
        self.current_question_index += 1
        if len(self.question_queue) > 0:
            r = self.question_queue.pop(0)
            self.question_history.append(r)
            return r
        return None

    def teardown(self):
        """
        Cleanup method
        """
        self.state = State.DONE
        if not self.question_answered_event.is_set():
            self.question_answered_event.set()
        self.dm_registration.deregister()
