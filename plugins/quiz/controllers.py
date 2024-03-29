import asyncio
import random
from enum import Enum
from datetime import datetime, timedelta

from nextcord import User, Embed, TextChannel
from nextcord.abc import Messageable
from nextcord.utils import get

from services.reactions import ReactionRemovedEvent, BaseReactionEvent
from services import timers
from botutils import statemachine
from botutils.utils import add_reaction
from botutils.stringutils import format_andlist
from base.data import Storage, Lang

from plugins.quiz.base import BaseQuizController, Score, InvalidAnswer, Difficulty, Rankedness
from plugins.quiz.utils import get_best_username


class QuizEnded(Exception):
    """
    To be raised by the Quiz class on get_question() if the quiz has ended (for whatever reason)
    """
    pass


class Phases(Enum):
    """
    Quiz phases for statemachine
    """
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
    def __init__(self, plugin, quizapi, channel: Messageable, requester: User, **kwargs):
        """
        :param plugin: Plugin object
        :param quizapi: Quiz API class that is to be used
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, quizapi, channel, requester, **kwargs)
        plugin.logger.debug("Building PointsQuizController; kwargs: {}".format(kwargs))
        self.cmdstring_register = "register"

        self.channel = channel
        self.requester = requester
        self.plugin = plugin
        self.task = asyncio.current_task()

        self.ranked = Rankedness.UNRANKED
        if "ranked" in kwargs:
            self.ranked = kwargs["ranked"]
        self.original_rankedness = self.ranked

        # QuizAPI config
        self.category = None if "category" not in kwargs else kwargs["category"]
        self.debug = True if "debug" in kwargs and kwargs["debug"] else False
        self.gecki = True if "gecki" in kwargs and kwargs["gecki"] else False
        self.noping = True if "noping" in kwargs and kwargs["noping"] else False
        self.question_count = kwargs["question_count"]
        self.difficulty = kwargs["difficulty"]

        self.quizapi = quizapi
        self._score = Score(self.plugin, self.question_count)

        # State handling
        self.eval_event = None
        self.stopped_manually = False
        self.ran_into_timeout = False
        self.current_question = None
        self.current_question_timer = None
        self.current_reaction_listener = None
        self.statemachine = statemachine.StateMachine(init_state=Phases.INIT)
        self.statemachine.add_state(Phases.REGISTERING, self.registering_phase, allowed_sources=[], start=True)
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

    #####
    # Transitions
    #####
    async def registering_phase(self):
        """
        REGISTERING -> [ABOUTTOSTART, ABORT]

        :return: Phases.ABOUTTOSTART or Phases.ABORT
        """
        self.plugin.logger.debug("Starting PointsQuizController")
        reaction = Lang.lang(self.plugin, "reaction_signup")
        signup_msg = Lang.lang(self.plugin, "registering_phase", reaction,
                               self.plugin.get_config("points_quiz_register_timeout") // 60)
        if self.plugin.role is not None and not self.noping:
            signup_msg = "{}\n{}".format(signup_msg, self.plugin.role.mention)
        signup_msg = await self.channel.send(signup_msg)
        await add_reaction(signup_msg, Lang.lang(self.plugin, "reaction_signup"))

        before = datetime.now()
        await self.quizapi.fetch()
        tosleep = datetime.now() - before
        await asyncio.sleep(self.plugin.get_config("points_quiz_register_timeout") - tosleep.seconds)

        # Consume signup reactions
        await signup_msg.remove_reaction(Lang.lang(self.plugin, "reaction_signup"), self.plugin.bot.user)
        signup_msg = get(self.plugin.bot.cached_messages, id=signup_msg.id)
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

        # Decide Rankedness
        if players < self.plugin.get_config("ranked_min_players") and not self.debug:
            if self.ranked == Rankedness.AUTO:
                self.ranked = Rankedness.UNRANKED
            elif self.ranked == Rankedness.RANKED:
                return Phases.ABORT
        else:
            if self.ranked == Rankedness.AUTO:
                self.ranked = Rankedness.RANKED
        self.plugin.logger.debug("Rankedness: %s", self.ranked)

        if players == 0:
            await self.channel.send(Lang.lang(self.plugin, "quiz_no_players"))
            return Phases.ABORT
        return Phases.ABOUTTOSTART

    async def about_to_start(self):
        """
        ABOUTTOSTART -> QUESTION; ABOUTTOSTART -> ABORT

        :return: Phases.QUESTION
        """
        self.plugin.logger.debug("Ending the registering phase")

        if len(self.registered_participants) == 0:
            # abort
            embed, msg = self.plugin.end_quiz(self.channel)
            await self.channel.send(msg, embed=embed)
            return

        for user in self.registered_participants:
            self.score.add_participant(user)
        embed = Embed(title=Lang.lang(self.plugin, "quiz_phase"))
        value = "\n".join([get_best_username(Storage().get(self.plugin), el, mention=True)
                           for el in self.registered_participants])
        embed.add_field(name="Participants:", value=value)
        await self.channel.send(embed=embed)

        await asyncio.sleep(10)
        return Phases.QUESTION

    async def pose_question(self) -> Phases:
        """
        QUESTION -> [EVAL, END]

        :return: Phases.EVAL or Phases.END
        """
        self.plugin.logger.debug("Posing next question.")
        try:
            self.current_question = self.quizapi.next_question()
        except QuizEnded:
            self.plugin.logger.debug("Caught QuizEnded, will end the quiz now.")
            return Phases.END

        self.eval_event = asyncio.Event()
        self.current_question_timer = timers.Timer(self.plugin.bot,
                                                   self.plugin.get_config("points_quiz_question_timeout"),
                                                   self.timeout_warning,
                                                   self.eval_event)
        msg = await self.current_question.pose(self.channel, emoji=self.plugin.get_config("emoji_in_pose"))
        self.current_reaction_listener = self.plugin.bot.reaction_listener.register(
            msg, self.on_reaction, data=self.current_question)
        if self.plugin.get_config("emoji_in_pose"):
            await self.current_question.add_reactions(msg)

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

    async def eval(self) -> Phases:
        """
        EVAL -> QUESTION
        Is called when the question is over. Evaluates scores and cancels the timer.

        :return: Phases.QUESTION
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
            self.current_reaction_listener.deregister()

        question = self.quizapi.current_question()

        # Normalize answers
        for key, el in self.registered_participants.items():
            if len(el) != 1:
                self.registered_participants[key] = None
            else:
                self.registered_participants[key] = el[0]

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
        if self.plugin.get_config("emoji_in_pose"):
            ca = question.correct_answer_emoji
        else:
            ca = question.correct_answer_letter
        await self.channel.send(Lang.lang(self.plugin, "points_question_done", ca, correct))

        # Reset answers list
        self.answers_order = []
        for user in self.registered_participants:
            self.registered_participants[user] = []

        await asyncio.sleep(self.plugin.get_config("question_cooldown"))
        return Phases.QUESTION

    async def end(self):
        """
        Called when the quiz ends
        """
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

        if self.ranked == Rankedness.RANKED:
            for player in self.registered_participants:
                self.plugin.update_ladder(player, self.score.calc_points(player))

        self.plugin.end_quiz(self.channel)

    async def abortphase(self):
        """
        Called when the quiz is aborted
        """
        self.plugin.logger.debug("Aborting quiz")
        self.plugin.end_quiz(self.channel)
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except timers.HasAlreadyRun:
                pass
        if self.original_rankedness == Rankedness.RANKED \
                and len(self.registered_participants) < self.plugin.get_config("ranked_min_players") \
                and not self.stopped_manually:
            await self.channel.send(Lang.lang(self.plugin, "ranked_playercount",
                                              self.plugin.get_config("ranked_min_players")))
        else:
            await self.channel.send(Lang.lang(self.plugin, "quiz_abort"))

    def cleanup(self):
        if self.current_question_timer is not None:
            try:
                self.current_question_timer.cancel()
            except timers.HasAlreadyRun:
                pass

    ###
    # Callbacks
    ###
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

    async def on_reaction(self, event: BaseReactionEvent):
        if event.member == self.plugin.bot.user:
            self.plugin.logger.debug("Caught self-reaction: {} on {}".format(event.emoji, event.message))
            return
        self.plugin.logger.debug("Caught reaction: {} on {}".format(event.emoji, event.message))

        # Cases we don't care about
        if self.state != Phases.QUESTION or self.current_question != event.data:
            return
        if event.member not in self.registered_participants:
            # register user if not ranked and answer is valid
            if not self.ranked == Rankedness.RANKED and \
                    self.quizapi.current_question().is_valid_emoji(event.emoji.name):
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

    ###
    # Timers stuff; these functions are scheduled by timers only
    ###
    async def timeout_warning(self, event):
        """
        :param event: Eval event that is to be set after the timeout
        """
        if self.eval_event != event:
            # We are out of date
            self.plugin.logger.debug("Timeout warning out of date")
            return

        self.plugin.logger.debug("Question timeout warning")
        self.current_question_timer = timers.Timer(self.plugin.bot,
                                                   self.plugin.get_config("points_quiz_question_timeout") // 2,
                                                   self.timeout, event)

        msg = Lang.lang(self.plugin, "points_timeout_warning",
                        format_andlist(self.havent_answered_hr(),
                                       ands=Lang.lang(self.plugin, "and"),
                                       fulllist=Lang.lang(self.plugin, "everyone"),
                                       fulllen=len(self.registered_participants)),
                        self.plugin.get_config("points_quiz_question_timeout") // 2)
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

    ###
    # Commands
    ###
    async def start(self, msg):
        """
        Called when the start command is invoked.
        """
        self.plugin.logger.debug("category: {}".format(self.category))
        self.quizapi = self.quizapi(self.channel,
                                    self.category,
                                    self.question_count,
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
        if self.state in (Phases.INIT, Phases.REGISTERING):
            title = Lang.lang(self.plugin, "status_title_init")
        else:
            title = Lang.lang(self.plugin,
                              "status_title_ingame",
                              self.quizapi.current_question_index() + 1,
                              len(self.quizapi))
        embed = Embed(title=title)
        catname = self.plugin.category_controller.get_name_by_category_key(self.quizapi, self.category)
        embed.add_field(name="Category", value=catname)
        embed.add_field(name="Difficulty", value=Difficulty.human_readable(self.difficulty))
        embed.add_field(name="Mode", value="Points (Everyone answers)")
        embed.add_field(name="Questions", value=str(self.question_count))

        if not self.state == Phases.INIT:
            status = ":arrow_forward: Running"
            if self.state == Phases.REGISTERING:
                status = ":book: Signup phase"
            #    status = ":pause_button: Paused"
            embed.add_field(name="Status", value=status)

        if self.ranked == Rankedness.RANKED:
            embed.add_field(name="Ranked", value=":memo:")
        elif self.ranked == Rankedness.AUTO:
            embed.add_field(name="Ranked", value=":hourglass_flowing_sand:")

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

    ###
    # Utils
    ###
    @property
    def state(self):
        return self.statemachine.state

    def has_everyone_answered(self):
        return not self.havent_answered_hr()

    def havent_answered_hr(self):
        return [get_best_username(Storage().get(self.plugin), key)
                for key, el in self.registered_participants.items() if len(el) != 1]


class RushQuizController(BaseQuizController):
    """
    Gamemode: the first user with the correct answer gets the point for the round
    """
    def __init__(self, plugin, quizapi, channel, requester, **kwargs):
        """
        :param plugin: Plugin object
        :param quizapi: BaseQuizAPI object
        :param channel: channel that the quiz was requested in
        :param requester: user that requested the quiz
        :param kwargs: category, question_count, difficulty, debug
        """
        super().__init__(plugin, quizapi, channel, requester, **kwargs)
        plugin.logger.debug("Building RushQuizController; quizapi: {}, channel: {}, requester: {}, kwargs: {}".format(
            quizapi, channel, requester, kwargs))
        self.plugin = plugin
        self.channel = channel
        self.requester = requester
        self.task = asyncio.current_task()

        # QuizAPI config
        self.category = None if "category" not in kwargs else kwargs["category"]
        self.noping = True if "noping" in kwargs and kwargs["noping"] else False
        self.debug = True if "debug" in kwargs and kwargs["debug"] else False
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
        self.last_author_time = None
        self.quizapi = quizapi
        self._score = Score(self.plugin, self.question_count)

    ###
    # Transitions
    ###
    async def about_to_start(self):
        """
        INIT -> QUESTION

        :return: QUESTION
        """
        startmsg = Lang.lang(self.plugin, "quiz_phase")
        if self.plugin.role is not None and not self.noping:
            startmsg = "{}\n{}".format(startmsg, self.plugin.role.mention)
        await self.channel.send(startmsg)
        await asyncio.sleep(10)
        return Phases.QUESTION

    async def pose_question(self):
        """
        QUESTION -> [EVAL, ABORT, END]
        :return: EVAL, ABORT or END
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
        self.plugin.logger.debug("Woken up.")
        self.eval_event = None
        if self.statemachine.cancelled():
            return Phases.ABORT
        return Phases.EVAL

    async def eval(self):
        """
        EVAL -> QUESTION
        Is called when the question is over. Evaluates scores and cancels the timer.
        :return: Phases.QUESTION
        """
        self.plugin.logger.debug("Ending question")

        question = self.quizapi.current_question()

        # Increment score
        self.score.increase(self.last_author, question)
        await self.channel.send(Lang.lang(self.plugin, "correct_answer",
                                          get_best_username(Storage().get(self.plugin), self.last_author),
                                          question.correct_answer_letter))

        await asyncio.sleep(self.plugin.get_config("question_cooldown"))
        return Phases.QUESTION

    async def end(self):
        """
        Is called when the quiz is over.
        """

        embed = self.score.embed()
        winners = [get_best_username(Storage().get(self.plugin), x) for x in self.score.winners()]

        # Übergangslösung
        points = self.score.points()
        for user, userpoints in points.items():
            self.plugin.update_ladder(user, userpoints)

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
        if not isinstance(msg.channel, TextChannel):
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

        t = self.last_author_time and datetime.now() - self.last_author_time < timedelta(seconds=10)
        if not self.debug and self.last_author == msg.author and t:
            uname = get_best_username(Storage().get(self.plugin), msg.author)
            await msg.channel.send(Lang.lang(self.plugin, "answering_order", uname))
            return

        self.last_author = msg.author
        self.last_author_time = datetime.now()
        if check:
            self.eval_event.set()
        await add_reaction(msg, Lang.lang(self.plugin, reaction))

    async def abortphase(self):
        await self.channel.send("The quiz was aborted.")
        self.plugin.end_quiz(self.channel)

    ###
    # Commands
    ###
    async def start(self, msg):
        self.quizapi = self.quizapi(self.channel, self.category, self.question_count,
                                    difficulty=self.difficulty, debug=self.debug)
        await self.quizapi.fetch()
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
        embed = Embed(title=title)
        catname = self.plugin.category_controller.get_name_by_category_key(self.quizapi, self.category)
        embed.add_field(name="Category", value=catname)
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

    def cleanup(self):
        self.statemachine.cancel()

    async def abort(self, msg):
        self.cleanup()
        await add_reaction(msg, Lang.CMDSUCCESS)

    @property
    def state(self):
        return self.statemachine.state
