import asyncio
import random
from enum import Enum
from datetime import datetime

import discord

from botutils.utils import add_reaction
from subsystems.reactions import ReactionRemovedEvent
from subsystems import timers
from botutils import statemachine
from botutils.stringutils import format_andlist
from conf import Storage, Lang

from plugins.quiz.abc import BaseQuizController
from plugins.quiz.base import Score, InvalidAnswer, Difficulty
from plugins.quiz.utils import get_best_username


class QuizEnded(Exception):
    """
    To be raised by the Quiz class on get_question() if the quiz has ended (for whatever reason)
    """
    pass


class Phases(Enum):
    INIT = 0
    REGISTERING = 1
    ABOUTTOSTART = 2
    QUESTION = 3
    EVAL = 4
    END = 5
    ABORT = 6


class PointsQuizController(BaseQuizController):
    """
    Gamemode: every user with the correct answer gets a point
    """
    def __init__(self, plugin, config, quizapi, channel, requester, **kwargs):
        """
        :param plugin: Plugin object
        :param config: config
        :param quizapi: BaseQuizAPI object
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, config, quizapi, channel, requester, **kwargs)
        plugin.logger.debug("Building PointsQuizController; kwargs: {}".format(kwargs))
        self.cmdstring_register = "register"

        self.channel = channel
        self.requester = requester
        self.config = config
        self.plugin = plugin

        self.ranked = False
        if "ranked" in kwargs:
            self.ranked = kwargs["ranked"]

        # QuizAPI config
        self.category = None
        if "category" in kwargs:
            self.category = kwargs["category"]
        self.debug = False
        if "debug" in kwargs and kwargs["debug"]:
            self.debug = True
        self.gecki = False
        if "gecki" in kwargs and kwargs["gecki"]:
            self.gecki = True
        self.question_count = kwargs["question_count"]
        self.difficulty = kwargs["difficulty"]

        self.quizapi = quizapi
        self._score = Score(self.plugin, self.config, self.question_count)

        # State handling
        self.eval_event = None
        self.stopped_manually = False
        self.ran_into_timeout = False
        self.current_question = None
        self.current_question_timer = None
        self.current_reaction_listener = None
        self.statemachine = statemachine.StateMachine(init_state=Phases.INIT)
        self.statemachine.add_state(Phases.REGISTERING, self.registering_phase, start=True)
        self.statemachine.add_state(Phases.ABOUTTOSTART, self.about_to_start, allowed_sources=[Phases.REGISTERING])
        self.statemachine.add_state(Phases.QUESTION, self.pose_question,
                                    allowed_sources=[Phases.ABOUTTOSTART, Phases.EVAL])
        self.statemachine.add_state(Phases.EVAL, self.eval, allowed_sources=[Phases.QUESTION])
        self.statemachine.add_state(Phases.END, self.end, allowed_sources=[Phases.QUESTION], end=True)
        self.statemachine.add_state(Phases.ABORT, self.abortphase, end=True)

        # Participant handling
        self.registered_participants = {}
        self.answers_order = []

    def register_participant(self, user):
        self.registered_participants[user] = []

    """
    Transitions
    """
    async def registering_phase(self):
        """
        REGISTERING -> ABOUTTOSTART; REGISTERING -> ABORT
        """
        self.plugin.logger.debug("Starting PointsQuizController")
        reaction = Lang.lang(self.plugin, "reaction_signup")
        signup_msg = await self.channel.send(Lang.lang(self.plugin, "registering_phase", reaction,
                                                       self.config["points_quiz_register_timeout"] // 60))
        await signup_add_reaction(msg, Lang.lang(self.plugin, "reaction_signup"))

        before = datetime.now()
        await self.quizapi.fetch()
        tosleep = before - datetime.now()
        await asyncio.sleep(self.config["points_quiz_register_timeout"] - tosleep.seconds)

        # Kwiss was cancelled
        if self.state != Phases.REGISTERING:
            return

        # Consume signup reactions
        await signup_msg.remove_reaction(Lang.lang(self.plugin, "reaction_signup"), self.plugin.bot.user)
        signup_msg = discord.utils.get(self.plugin.bot.cached_messages, id=signup_msg.id)
        reaction = None
        for el in signup_msg.reactions:
            if el.emoji == Lang.lang(self.plugin, "reaction_signup"):
                reaction = el
                break

        if reaction is not None:
            async for user in reaction.users():
                if user == self.plugin.bot.user:
                    continue

                found = False
                for el in self.registered_participants:
                    if el == user:
                        found = True
                        break
                if found:
                    # User already registered via !kwiss register
                    continue

                self.register_participant(user)
            if self.gecki:
                self.register_participant(self.plugin.bot.user)

        players = len(self.registered_participants)
        if players == 0 or (self.ranked and players < self.config["ranked_min_players"] and not self.debug):
            await self.channel.send(Lang.lang(self.plugin, "quiz_no_players"))
            return Phases.ABORT
        else:
            return Phases.ABOUTTOSTART

    async def about_to_start(self):
        """
        ABOUTTOSTART -> QUESTION; ABOUTTOSTART -> ABORT
        """
        self.plugin.logger.debug("Ending the registering phase")

        abort = False
        if len(self.registered_participants) == 0:
            abort = True
        if abort:
            embed, msg = self.plugin.end_quiz(self.channel)
            self.channel.send(msg, embed=embed)
            return
        else:
            for user in self.registered_participants:
                self.score.add_participant(user)
            embed = discord.Embed(title=Lang.lang(self.plugin, "quiz_phase"))
            value = "\n".join([get_best_username(Storage().get(self.plugin), el, mention=True)
                               for el in self.registered_participants])
            embed.add_field(name="Participants:", value=value)
            await self.channel.send(embed=embed)

        await asyncio.sleep(10)
        return Phases.QUESTION

    async def pose_question(self):
        """
        QUESTION -> EVAL; QUESTION -> END
        """
        self.plugin.logger.debug("Posing next question.")
        try:
            self.current_question = self.quizapi.next_question()
        except QuizEnded:
            self.plugin.logger.debug("Caught QuizEnded, will end the quiz now.")
            return Phases.END

        self.eval_event = asyncio.Event()
        self.current_question_timer = timers.AsyncTimer(self.plugin.bot, self.config["points_quiz_question_timeout"],
                                                        self.timeout_warning, self.eval_event)
        msg = await self.current_question.pose(self.channel, emoji=self.config["emoji_in_pose"])
        self.current_reaction_listener = self.plugin.bot.reaction_listener.register(
            msg, self.on_reaction, data=self.current_question)

        # If debug, add bot's answer
        if self.gecki:
            self.plugin.logger.debug("Adding bot's answer")
            found = None
            correct = random.choice([True, False])
            self.plugin.logger.debug("Gecki is going to answer with a {} answer".format(correct))
            for i in range(len(self.current_question.all_answers)):
                if self.current_question.all_answers[i] == self.current_question.correct_answer:
                    if correct:
                        found = i
                        break
                if not correct:
                    found = i
                    break
            answer = self.current_question.letter_mapping(found, emoji=True)
            self.registered_participants[self.plugin.bot.user] = [answer]
            self.answers_order.append(self.plugin.bot.user)

        # Wait for answers or timeout
        await self.eval_event.wait()
        self.eval_event = None
        return Phases.EVAL

    async def eval(self):
        """
        Is called when the question is over. Evaluates scores and cancels the timer.
        :return:
        """
        self.plugin.logger.debug("Ending question")

        # End timeout timer
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except timers.HasAlreadyRun:
                self.plugin.logger.warning("This should really, really not happen.")
            self.current_question_timer = None
        else:
            # We ran into a timeout and need to give that function time to communicate this fact
            await asyncio.sleep(1)

        if self.current_reaction_listener is not None:
            self.current_reaction_listener.unregister()

        question = self.quizapi.current_question()

        # Normalize answers
        for el in self.registered_participants:
            if len(self.registered_participants[el]) != 1:
                self.registered_participants[el] = None
            else:
                self.registered_participants[el] = self.registered_participants[el][0]

        # Increment scores
        correctly_answered = []
        for user in self.answers_order:
            if question.check_answer(self.registered_participants[user], emoji=True):
                correctly_answered.append(user)

        for user in correctly_answered:
            self.score.increase(user, self.current_question, totalcorr=len(correctly_answered))

        correct = [get_best_username(Storage().get(self.plugin), el) for el in correctly_answered]
        correct = format_andlist(correct,
                                 ands=Lang.lang(self.plugin, "and"),
                                 emptylist=Lang.lang(self.plugin, "nobody"),
                                 fulllist=Lang.lang(self.plugin, "everyone"),
                                 fulllen=len(self.registered_participants))
        if self.config["emoji_in_pose"]:
            ca = question.correct_answer_emoji
        else:
            ca = question.correct_answer_letter
        await self.channel.send(Lang.lang(self.plugin, "points_question_done", ca, correct))

        # Reset answers list
        self.answers_order = []
        for user in self.registered_participants:
            self.registered_participants[user] = []

        await asyncio.sleep(self.config["question_cooldown"])
        return Phases.QUESTION

    async def end(self):
        self.plugin.logger.debug("Ending quiz")
        embed = self.score.embed()
        winners = [get_best_username(Storage().get(self.plugin), x) for x in self.score.winners()]

        msgkey = "quiz_end"
        if len(winners) > 1:
            msgkey = "quiz_end_pl"
        elif len(winners) == 0:
            msgkey = "quiz_end_no_winner"
        fulllen = len(self.registered_participants)
        if fulllen <= 1:
            fulllen = None
        winners = format_andlist(winners,
                                 ands=Lang.lang(self.plugin, "and"),
                                 emptylist=Lang.lang(self.plugin, "nobody"),
                                 fulllist=Lang.lang(self.plugin, "everyone"),
                                 fulllen=fulllen)
        msg = Lang.lang(self.plugin, msgkey, winners)
        if msg is None:
            await self.channel.send(embed=embed)
        elif embed is None:
            await self.channel.send(msg)
        else:
            await self.channel.send(msg, embed=embed)

        if self.ranked:
            for player in self.registered_participants:
                self.plugin.update_ladder(player, self.score.calc_points(player))

        self.plugin.end_quiz(self.channel)

    async def abortphase(self):
        self.plugin.logger.debug("Aborting quiz")
        self.plugin.end_quiz(self.channel)
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except timers.HasAlreadyRun:
                pass
        if self.ranked \
                and len(self.registered_participants) < self.config["ranked_min_players"] \
                and not self.stopped_manually:
            await self.channel.send(Lang.lang(self.plugin, "ranked_playercount", self.config["ranked_min_players"]))
        else:
            await self.channel.send(Lang.lang(self.plugin, "quiz_abort"))

    """
    Callbacks
    """
    async def on_message(self, msg):
        return

    def continue_event(self, event):
        """
        Gracefully continues after waiting for question answers
        :param event: Eval event that is to be set
        """
        if event == self.eval_event:
            self.plugin.logger.debug("Continuing after waiting for answers")
            self.eval_event.set()

    async def on_reaction(self, event):
        if event.member == self.plugin.bot.user:
            self.plugin.logger.debug("Caught self-reaction: {} on {}".format(event.emoji, event.message))
            return
        self.plugin.logger.debug("Caught reaction: {} on {}".format(event.emoji, event.message))

        # Cases we don't care about
        if self.state != Phases.QUESTION or self.current_question != event.data:
            return
        if event.member not in self.registered_participants:
            # register user if not ranked and answer is valid
            if not self.ranked and self.quizapi.current_question().is_valid_emoji(event.emoji.name):
                self.register_participant(event.member)
                await self.channel.send(Lang.lang(self.plugin,
                                                  "registration_late",
                                                  get_best_username(Storage().get(self.plugin), event.member)))
            else:
                return

        # Reaction removed
        if isinstance(event, ReactionRemovedEvent):
            self.registered_participants[event.member].remove(event.emoji)
            if not self.registered_participants[event.member]:
                self.answers_order.remove(event.member)
            return

        # Check / validate answer
        try:
            check = self.quizapi.current_question().check_answer(event.emoji, emoji=True)
            if check:
                check = "correct"
            else:
                check = "incorrect"
            self.plugin.logger.debug("Valid answer from {}: {} ({})"
                                     .format(event.member.name, event.emoji, check))
        except InvalidAnswer:
            return

        # Register answer
        self.registered_participants[event.member].append(event.emoji)
        if event.member not in self.answers_order:
            self.answers_order.append(event.member)
        if not self.havent_answered_hr():
            self.plugin.logger.debug("Everyone has answered, continuing")
            self.continue_event(self.eval_event)

    """
    Timers stuff; these functions are scheduled by timers only
    """
    async def timeout_warning(self, event):
        """
        :param event: Eval event that is to be set after the timeout
        """
        if self.eval_event != event:
            # We are out of date
            self.plugin.logger.debug("Timeout warning out of date")
            return

        self.plugin.logger.debug("Question timeout warning")
        self.current_question_timer = timers.AsyncTimer(self.plugin.bot,
                                                        self.config["points_quiz_question_timeout"] // 2,
                                                        self.timeout, event)

        msg = Lang.lang(self.plugin, "points_timeout_warning",
                        format_andlist(self.havent_answered_hr(),
                                       ands=Lang.lang(self.plugin, "and"),
                                       fulllist=Lang.lang(self.plugin, "everyone"),
                                       fulllen=len(self.registered_participants)),
                        self.config["points_quiz_question_timeout"] // 2)
        panic = not self.havent_answered_hr()
        await self.channel.send(msg)
        if panic:
            await self.channel.send("I know this should not happen. Please leave a `!complain`, thank you very much.")

    async def timeout(self, event):
        """
        :param event: Eval event that is to be set after the timeout
        """
        if self.eval_event != event:
            # We are out of date
            self.plugin.logger.debug("Timeout warning out of date")
            return

        self.current_question_timer = None
        self.plugin.logger.debug("Question timeout")
        msg = Lang.lang(self.plugin, "points_timeout", self.quizapi.current_question_index(),
                        format_andlist(self.havent_answered_hr(),
                                       ands=Lang.lang(self.plugin, "and"),
                                       fulllist=Lang.lang(self.plugin, "everyone"),
                                       fulllen=len(self.registered_participants)))
        await self.channel.send(msg)
        self.continue_event(event)

    """
    Commands
    """
    async def start(self, msg):
        """
        Called when the start command is invoked.
        """
        # Fetch questions
        self.plugin.logger.debug("category: {}".format(self.category))
        self.quizapi = self.quizapi(self.config,
                                    self.channel,
                                    category=self.category,
                                    question_count=self.question_count,
                                    difficulty=self.difficulty,
                                    debug=self.debug)
        await self.statemachine.run()

    async def register_command(self, msg, *args):
        """
        This is the callback for !kwiss register.
        :param msg: Message object
        :param args: Passed arguments, including "register"
        """
        assert self.cmdstring_register in args

        if len(args) > 1:
            await self.channel.send(Lang.lang(self.plugin, "too_many_arguments"))
            return

        if self.state == Phases.INIT:
            await self.channel.send("No idea how you did that, but you registered too early.")
            return

        if self.state != Phases.REGISTERING:
            await self.channel.send(Lang.lang(self.plugin, "registering_too_late", msg.author))
            return

        if msg.author in self.registered_participants:
            return

        self.registered_participants[msg.author] = []
        self.score.add_participant(msg.author)
        self.plugin.logger.debug("{} registered".format(msg.author.name))
        await add_reaction(msg, Lang.CMDSUCCESS)
        # await self.channel.send(message(self.config, "register_success", msg.author))

    async def pause(self, msg):
        """
        Called when the pause command is invoked.
        """
        raise NotImplementedError

    async def resume(self, msg):
        """
        Called when the resume command is invoked.
        """
        raise NotImplementedError

    async def status(self, msg):
        """
        Called when the status command is invoked.
        """
        if self.state == Phases.INIT or self.state == Phases.REGISTERING:
            title = Lang.lang(self.plugin, "status_title_init")
        else:
            title = Lang.lang(self.plugin,
                              "status_title_ingame",
                              self.quizapi.current_question_index() + 1,
                              len(self.quizapi))
        embed = discord.Embed(title=title)
        embed.add_field(name="Category", value=self.quizapi.category_name(self.category))
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Points (Everyone answers)")
        embed.add_field(name="Questions", value=str(self.question_count))

        if not self.state == Phases.INIT:
            status = ":arrow_forward: Running"
            if self.state == Phases.REGISTERING:
                status = ":book: Signup phase"
            #    status = ":pause_button: Paused"
            embed.add_field(name="Status", value=status)

        if self.ranked:
            embed.add_field(name="Ranked", value=":memo:")

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        if self.gecki:
            embed.add_field(name="Gecki", value="I'm in! 😍")

        embed.add_field(name="Initiated by", value=get_best_username(Storage().get(self.plugin), self.requester))

        await self.channel.send(embed=embed)

    async def abort(self, msg):
        """
        Called when the quiz is aborted.
        """
        self.stopped_manually = True
        await add_reaction(msg, Lang.CMDSUCCESS)
        return Phases.ABORT

    @property
    def score(self):
        """
        :return: Score object
        """
        return self._score

    """
    Utils
    """
    @property
    def state(self):
        return self.statemachine.state

    def has_everyone_answered(self):
        if self.havent_answered_hr():
            return False
        else:
            return True

    def havent_answered_hr(self):
        return [get_best_username(Storage().get(self.plugin), el)
                for el in self.registered_participants if len(self.registered_participants[el]) != 1]


class RushQuizController(BaseQuizController):
    """
    Gamemode: the first user with the correct answer gets the point for the round
    """
    def __init__(self, plugin, config, quizapi, channel, requester, **kwargs):
        """
        :param plugin: Plugin object
        :param config: config
        :param quizapi: BaseQuizAPI object
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, config, quizapi, channel, requester, **kwargs)
        plugin.logger.debug("Building RaceQuizController; kwargs: {}".format(kwargs))
        self.config = config
        self.plugin = plugin
        self.channel = channel
        self.requester = requester

        # QuizAPI config
        self.category = None
        if "category" in kwargs:
            self.category = kwargs["category"]
        self.debug = False
        if "debug" in kwargs and kwargs["debug"]:
            self.debug = True
        self.question_count = kwargs["question_count"]
        self.difficulty = kwargs["difficulty"]

        # State handling
        self.eval_event = None
        self.current_question = None
        self.current_question_timer = None
        self.statemachine = statemachine.StateMachine(init_state=Phases.INIT)
        self.statemachine.add_state(Phases.ABOUTTOSTART, self.about_to_start, start=True)
        self.statemachine.add_state(Phases.QUESTION, self.pose_question, [Phases.ABOUTTOSTART, Phases.EVAL])
        self.statemachine.add_state(Phases.EVAL, self.eval, [Phases.QUESTION])
        self.statemachine.add_state(Phases.END, self.end, [Phases.QUESTION], end=True)
        self.statemachine.add_state(Phases.ABORT, self.abortphase, None, end=True)

        # Quiz handling
        self.last_author = None
        self.quizapi = quizapi
        self._score = Score(self.plugin, self.config, self.question_count)

    """
    Transitions
    """
    async def about_to_start(self):
        await self.channel.send(Lang.lang(self.plugin, "quiz_phase"))
        await asyncio.sleep(10)
        if self.statemachine.cancelled():
            return Phases.ABORT
        return Phases.QUESTION

    async def pose_question(self):
        """
        QUESTION -> EVAL
        """
        self.eval_event = asyncio.Event()
        self.last_author = None
        self.plugin.logger.debug("Posing next question.")
        try:
            self.current_question = self.quizapi.next_question()
        except QuizEnded:
            self.plugin.logger.debug("Caught QuizEnded, will end the quiz now.")
            return Phases.END
        await self.current_question.pose(self.channel)

        await self.eval_event.wait()
        self.eval_event = None
        if self.statemachine.cancelled():
            return Phases.ABORT
        else:
            return Phases.EVAL

    async def eval(self):
        """
        Is called when the question is over. Evaluates scores and cancels the timer.
        :return:
        """
        self.plugin.logger.debug("Ending question")

        question = self.quizapi.current_question()

        # Increment score
        self.score.increase(self.last_author, question)
        await self.channel.send(Lang.lang(self.plugin, "correct_answer",
                                          get_best_username(Storage().get(self.plugin), self.last_author),
                                          question.correct_answer_letter))

        await asyncio.sleep(self.config["question_cooldown"])
        return Phases.QUESTION

    async def end(self):

        embed = self.score.embed()
        winners = [get_best_username(Storage().get(self.plugin), x) for x in self.score.winners()]

        # Übergangslösung
        points = self.score.points()
        for user in points:
            self.plugin.update_ladder(user, points[user])

        msgkey = "quiz_end"
        if len(winners) > 1:
            msgkey = "quiz_end_pl"
        elif len(winners) == 0:
            msgkey = "quiz_end_no_winner"
        winners = format_andlist(winners, ands=Lang.lang(self.plugin, "and"),
                                 emptylist=Lang.lang(self.plugin, "nobody"))
        msg = Lang.lang(self.plugin, msgkey, winners)

        if msg is None:
            await self.channel.send(embed=embed)
        elif embed is None:
            await self.channel.send(msg)
        else:
            await self.channel.send(msg, embed=embed)

        self.plugin.end_quiz(self.channel)

    async def on_message(self, msg):
        self.plugin.logger.debug("Caught message: {}".format(msg.content))
        # ignore DM and msg when the quiz is not in question phase
        if not isinstance(msg.channel, discord.TextChannel):
            return
        if self.state != Phases.QUESTION:
            self.plugin.logger.debug("Ignoring message, quiz is not in question phase")
            return

        # Valid answer
        try:
            check = self.quizapi.current_question().check_answer(msg.content)
            if check:
                reaction = "reaction_correct"
            else:
                reaction = "reaction_incorrect"
            self.plugin.logger.debug("Valid answer from {}: {} ({})".format(msg.author.name, msg.content, reaction))
        except InvalidAnswer:
            return

        if not self.debug and self.last_author == msg.author:
            await msg.channel.send(Lang.lang(self.plugin, "answering_order", msg.author))
            return

        self.last_author = msg.author
        if check:
            self.eval_event.set()
        await add_reaction(msg, Lang.lang(self.plugin, reaction))

    async def abortphase(self):
        await self.channel.send("The quiz was aborted.")
        self.plugin.end_quiz(self.channel)

    """
    Commands
    """
    async def start(self, msg):
        self.quizapi = self.quizapi(self.config, self.channel,
                                    category=self.category, question_count=self.question_count,
                                    difficulty=self.difficulty, debug=self.debug)
        await self.statemachine.run()

    async def pause(self, msg):
        raise NotImplementedError

    async def resume(self, msg):
        raise NotImplementedError

    async def status(self, msg):
        if self.state == Phases.INIT or self == Phases.ABOUTTOSTART:
            title = Lang.lang(self.plugin, "status_title_init")
        else:
            title = Lang.lang(self.plugin,
                              "status_title_ingame",
                              self.quizapi.current_question_index() + 1,
                              len(self.quizapi))
        embed = discord.Embed(title=title)
        embed.add_field(name="Category", value=self.quizapi.category_name(self.category))
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Rush (Winner takes it all)")
        embed.add_field(name="Initiated by", value=get_best_username(Storage().get(self.plugin), self.requester))

        status = ":arrow_forward: Running"
        #    status = ":pause_button: Paused"
        embed.add_field(name="Status", value=status)

        if self.debug:
            embed.add_field(name="Debug mode", value=":beetle:")

        await add_reaction(msg, Lang.CMDSUCCESS)
        await self.channel.send(embed=embed)

    @property
    def score(self):
        return self._score

    def stop(self):
        pass

    async def abort(self, msg):
        self.statemachine.cancel()
        await add_reaction(msg, Lang.CMDSUCCESS)

    """
    Utils
    """
    @property
    def state(self):
        return self.statemachine.state
