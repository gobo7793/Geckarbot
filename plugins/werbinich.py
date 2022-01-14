import logging
import asyncio
from enum import Enum
from datetime import datetime
from typing import Optional

from nextcord import ClientUser
from nextcord.ext import commands
from nextcord.http import HTTPException
from nextcord.errors import Forbidden
from nextcord.utils import get

from base.configurable import BasePlugin, NotFound
from base.data import Lang, Config
from botutils import utils, statemachine, stringutils
from botutils.converters import get_best_username as gbu
from botutils.stringutils import format_andlist
from botutils.utils import add_reaction
from services import presence
from services.helpsys import DefaultCategories
from services.reactions import ReactionAddedEvent, BaseReactionEvent


class State(Enum):
    """
    States for statemachine
    """
    IDLE = 0  # no whoami running
    REGISTER = 1  # registering phase
    COLLECT = 2  # messaging everyone and waiting for entries from participants
    DELIVER = 3  # messaging results to everyone
    ABORT = 4  # not everyone answered


class Participant:
    """
    Represents a werbinich participant
    """
    def __init__(self, plugin, user):
        self.plugin = plugin
        self.user = user
        self.assigned = None  # user this one has to choose for
        self.chosen = None
        self.registration = self.plugin.bot.dm_listener.register(self.user, self.dm_callback, "werbinich",
                                                                 blocking=True)
        self.plugin.logger.debug("New Participant: {}".format(user))

    def assign(self, p):
        """
        Assigns a participant. Can only be called once.

        :param p: Participant this one has to choose for
        :raises RuntimeError: Assignment algorithm assigned twice (bug)
        """
        if self.assigned is not None:
            raise RuntimeError("This participant already has an assigned participant")
        self.plugin.logger.debug("Assigning {} to {}".format(p, self.user))
        self.assigned = p

    async def kill_cb(self):
        """
        The DM registration has been killed, so we're killing the whole game.
        """
        await self.plugin.kill(self)

    async def init_dm(self):
        """
        Sends the initiation DM to the participant which explains things and asks for an entry.
        """
        self.plugin.logger.debug("Sending init DM to {}".format(self.user))
        await self.send(Lang.lang(self.plugin, "ask_for_entry", gbu(self.assigned.user)))

    async def dm_callback(self, reg, message):
        """
        DM callback method; handles any incoming DMs

        :param reg: Registration object
        :param message: Message content
        """
        self.plugin.logger.debug("Incoming message from %s: %s; reg: %s", str(self.user), message.content, str(reg))
        if message.content.strip() == "":
            # you never know
            return

        if self.plugin.statemachine.state != State.COLLECT:
            await self.send(Lang.lang(self.plugin, "entry_too_late"))
            return

        first = True
        if self.chosen:
            first = False

        self.chosen = message.content
        if first:
            await self.send(Lang.lang(self.plugin, "entry_done", gbu(self.assigned.user),
                                      self.chosen))
        else:
            await self.send(Lang.lang(self.plugin, "entry_change", self.chosen))

        self.plugin.assigned()

    async def send(self, msg):
        """
        Sends a DM to this user and logs it to debug.

        :param msg: Message content
        :return: return value of user.send()
        """
        self.plugin.logger.debug("Sending DM to {}: {}".format(self.user, msg))
        return await self.user.send(msg)

    def to_msg(self, show_assignees=True) -> str:
        """
        :param show_assignees: Flag that determines whether the assignee is to be shown
        :return: String that contains info about this participant and his assignment
        """
        if show_assignees:
            key = "result_with_assignees"
        else:
            key = "result_without_assignees"
        return Lang.lang(self.plugin, key, gbu(self.assigned.user), self.chosen, gbu(self.user))

    def cleanup(self):
        """
        Deregisters the DM channel for this user.
        """
        self.plugin.logger.debug("Cleaning up participant {}".format(self.user))
        if self.registration is not None:
            self.registration.deregister()
            self.registration = None

    def __str__(self):
        return "<Participant object for user '{}'>".format(self.user)


class Plugin(BasePlugin, name="Wer bin ich?"):
    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.GAMES)
        self.logger = logging.getLogger(__name__)

        self.channel = None
        self.initiator = None
        self.show_assignees = True
        self.postgame = False
        self.presence_message = None
        self.participants = []
        self.eval_event = None
        self.reg_ts = None
        self.spoiler_reaction_listener = None
        self.spoilered_users = []

        self.base_config = {
            "register_timeout": [int, 1],
        }

        self.eval_event = None
        self.reg_start_time = None
        self.statemachine = statemachine.StateMachine(init_state=State.IDLE)
        self.statemachine.add_state(State.IDLE, None)
        self.statemachine.add_state(State.REGISTER, self.registering_phase, start=True)
        self.statemachine.add_state(State.COLLECT, self.collecting_phase, allowed_sources=[State.REGISTER])
        self.statemachine.add_state(State.DELIVER, self.delivering_phase, allowed_sources=[State.COLLECT])
        self.statemachine.add_state(State.ABORT, self.abort)

    def get_config(self, key):
        return Config.get(self).get(key, self.base_config[key][1])

    def default_config(self, container=None):
        return {}

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.name))

    def command_description(self, command):
        msg = Lang.lang(self, "description_{}".format(command.name))
        if command.name == "werbinich":
            msg += Lang.lang(self, "options_werbinich")
        return msg

    def command_usage(self, command):
        if command.name == "werbinich":
            return Lang.lang(self, "usage_{}".format(command.name))
        raise NotFound()

    @commands.group(name="werbinich", invoke_without_command=True)
    async def cmd_werbinich(self, ctx, *args):
        # Argument parsing
        for arg in args:
            if arg == "geheim":
                self.show_assignees = False
            else:
                await ctx.send(Lang.lang(self, "unknown_argument", arg))
                return

        # Actual werbinich
        if self.statemachine.state != State.IDLE:
            await ctx.send(Lang.lang(self, "already_running"))
            return

        self.postgame = False
        self.channel = ctx.channel
        self.initiator = ctx.message.author
        await self.statemachine.run()

    @cmd_werbinich.command(name="status")
    async def cmd_status(self, ctx):
        if self.statemachine.state == State.IDLE:
            # Post-game and game in mem
            if self.channel is not None and self.postgame:
                msg = "{} {}".format(
                    Lang.lang(self, "post_game_status"),
                    Lang.lang(self, "past_game_in_mem", self.channel.mention))

            # Idle and game in mem but not postgame
            elif self.channel:
                msg = "{} {}".format(
                    Lang.lang(self, "not_running"),
                    Lang.lang(self, "past_game_in_mem", self.channel.mention))

            # No game in mem
            else:
                msg = Lang.lang(self, "not_running")

            await ctx.send(msg)
            return
        if self.statemachine.state == State.REGISTER:
            sec = self.get_config("register_timeout") * 60 - int((datetime.now() - self.reg_ts).total_seconds())
            await ctx.send(Lang.lang(self, "status_registering", sec))
            return
        if self.statemachine.state == State.DELIVER:
            await ctx.send(Lang.lang(self, "status_delivering"))
            return
        if self.statemachine.state == State.ABORT:
            await ctx.send(Lang.lang(self, "status_aborting"))
            return

        assert self.statemachine.state == State.COLLECT
        waitingfor = []
        for el in self.participants:
            if el.chosen is None:
                waitingfor.append(gbu(el.user))

        wf = stringutils.format_andlist(waitingfor, ands=Lang.lang(self, "and"), emptylist=Lang.lang(self, "nobody"))
        await ctx.send(Lang.lang(self, "waiting_for", wf))

    @cmd_werbinich.command(name="stop")
    async def cmd_stop(self, ctx):
        if self.statemachine.state == State.IDLE:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "not_running"))
            return
        await ctx.send("Sorry, das tut momentan nicht")
        await add_reaction(ctx.message, Lang.CMDERROR)
        # await add_reaction(ctx.message, Lang.CMDSUCCESS)
        # await self.cleanup()

    @cmd_werbinich.command(name="spoiler")
    async def cmd_spoiler(self, ctx):
        # State check
        error = None
        if self.statemachine.state != State.IDLE:
            error = "show_running"

        elif not self.participants:
            error = "show_not_found"

        elif ctx.author in [x.user for x in self.participants] and not self.postgame:
            error = "no_spoiler"

        if error is not None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, error))
            return

        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        for msg in stringutils.paginate(self.participants, prefix=Lang.lang(self, "participants_last_round"),
                                        f=lambda x: x.to_msg()):
            await ctx.author.send(msg)

    @cmd_werbinich.command(name="fertig")
    async def cmd_postgame(self, ctx):
        error = None
        if ctx.channel != self.channel:
            error = "wrong_channel"

        else:
            found = False
            for user in self.participants:
                if user.user == ctx.message.author:
                    found = True
                    break
            if not found:
                error = "postgame_unauthorized"

        if error is not None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, error))
            return

        # Actual cmd
        self.postgame = True
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_werbinich.command(name="del")
    async def cmd_del(self, ctx):
        if not self.participants:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        self.participants = []
        self.channel = None
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    ###
    # Transitions
    ###

    async def registering_phase(self) -> Optional[State]:
        """
        Transition REGISTER -> [COLLECT, ABORT]

        :return: new state
        """
        self.logger.debug("Starting registering phase")
        self.eval_event = asyncio.Event()
        self.postgame = False
        self.spoilered_users = []
        if self.spoiler_reaction_listener:
            self.spoiler_reaction_listener.deregister()
        self.presence_message = self.bot.presence.register(Lang.lang(self, "presence", self.channel.name),
                                                           priority=presence.PresencePriority.HIGH)
        reaction = Lang.lang(self, "reaction_signup")
        to = self.get_config("register_timeout")
        self.reg_ts = datetime.now()
        msg = Lang.lang(self, "registering", reaction, to,
                        stringutils.sg_pl(to, Lang.lang(self, "minute_sg"), Lang.lang(self, "minute_pl")))
        msg = await self.channel.send(msg)

        try:
            await add_reaction(msg, Lang.lang(self, "reaction_signup"))
        except HTTPException:
            # Unable to add reaction, therefore unable to begin the game
            await self.channel.send("PANIC")
            return State.ABORT

        self.reg_start_time = datetime.now()
        await asyncio.sleep(to * 60)
        if self.statemachine.cancelled():
            return None

        # Consume signup reactions
        self.participants = []
        await msg.remove_reaction(Lang.lang(self, "reaction_signup"), self.bot.user)
        signup_msg = get(self.bot.cached_messages, id=msg.id)
        reaction = None
        for el in signup_msg.reactions:
            if el.emoji == Lang.lang(self, "reaction_signup"):
                reaction = el
                break

        candidates = []
        blocked = []
        if reaction is not None:
            async for user in reaction.users():
                if user == self.bot.user:
                    continue

                if self.bot.dm_listener.is_blocked(user):
                    blocked.append(gbu(user))
                else:
                    candidates.append(user)

        if blocked:
            blocked = stringutils.format_andlist(blocked, ands=Lang.lang(self, "and"))
            await self.channel.send(Lang.lang(self, "dm_blocked", blocked))
            return State.ABORT

        for el in candidates:
            try:
                self.participants.append(Participant(self, el))
            except RuntimeError:
                await add_reaction(msg, Lang.CMDERROR)
                return State.ABORT

        players = len(self.participants)
        if players <= 1:
            await self.channel.send(Lang.lang(self, "no_participants"))
            return State.ABORT
        return State.COLLECT

    async def collecting_phase(self) -> Optional[State]:
        """
        Transition COLLECT -> [DELIVER, ABORT]

        :return: new state
        """
        assert len(self.participants) > 1

        msg = sorted([gbu(el.user) for el in self.participants], key=str.casefold)
        msg = stringutils.format_andlist(msg, ands=Lang.lang(self, "and"))
        msg = Lang.lang(self, "list_participants", msg)

        shuffled = self.participants.copy()
        utils.trueshuffle(shuffled)
        for i in range(len(self.participants)):
            self.participants[i].assign(shuffled[i])

        self.participants = sorted(self.participants, key=lambda x: gbu(x).lower())

        await self.channel.send(msg)
        errors = []
        for el in self.participants:
            try:
                await el.init_dm()
            except Forbidden:
                errors.append(el)

        # check for DM forbidden errors and cancel if necessary
        if errors:
            msg = [gbu(el.user) for el in errors]
            msg = Lang.lang(self, "blocked_by_user", format_andlist(msg, ands=Lang.lang(self, "and")))

            # Notify participants
            for el in self.participants:
                if el in errors:
                    continue
                await el.send(msg)
            await self.channel.send(msg)
            return State.ABORT

        await self.eval_event.wait()
        if self.statemachine.cancelled():
            for el in self.participants:
                await el.cancelled_dm()
            return None
        return State.DELIVER

    def assigned(self):
        """
        Sets eval_event.
        """
        for el in self.participants:
            if el.chosen is None:
                return
        self.eval_event.set()

    async def spoiler_dm(self, event: BaseReactionEvent):
        """
        Callback for reaction listener that sends a spoiler DM.

        :param event: Reaction event
        """
        if isinstance(event, ReactionAddedEvent) and event.emoji.name == Lang.lang(self, "reaction_spoiler") \
                and not isinstance(event.user, ClientUser):
            if self.statemachine.state == State.IDLE and self.participants \
                    and (event.user not in (x.user for x in self.participants) or self.postgame):
                if event.user in self.spoilered_users:
                    self.logger.debug("%s already got the spoiler but tried again.", event.user.name)
                    return
                # send dm
                try:
                    for msg in stringutils.paginate(self.participants,
                                                    prefix=Lang.lang(self, "participants_last_round"),
                                                    f=lambda x: x.to_msg()):
                        await event.user.send(msg)
                except Forbidden:
                    await event.channel.send(Lang.lang(self, "blocked_spoiler", event.user.mention))
                else:
                    self.spoilered_users.append(event.user)

    async def delivering_phase(self) -> None:
        """
        Transition DELIVER -> None
        """
        for target in self.participants:
            todo = []
            if self.show_assignees:
                for el in self.participants:
                    if el.assigned == target:
                        todo.append(Lang.lang(self, "user_assignee", gbu(el.user)))
            for el in self.participants:
                if el.assigned != target:
                    todo.append(el.to_msg(show_assignees=self.show_assignees))

            for msg in stringutils.paginate(todo, prefix=Lang.lang(self, "list_title")):
                await target.send(msg)
        done_msg = await self.channel.send(Lang.lang(self, "done"))
        await add_reaction(done_msg, Lang.lang(self, "reaction_spoiler"))
        self.spoiler_reaction_listener = self.bot.reaction_listener.register(done_msg, self.spoiler_dm, data=None)
        await self.cleanup()
        return None

    async def kill(self, participant):
        """
        Notifies the participant about a DM channel kill.

        :param participant: Participant whose DM channel was killed
        """
        await self.channel.send("Cancelling werbinich, {}'s DM registration was killed.".format(gbu(participant.user)))

    async def abort(self):
        """
        ABORT state; calls cleanup()
        """
        await self.cleanup()

    async def cleanup(self, exception: Exception = None):
        """
        Deregisters registrations, resets state and resets variables.

        :param exception: Exception; optional for when we are cleaning up because of an exception
        :raises Exception: When we are cleaning up because of an exception; simply raises `exception`
        """
        self.logger.debug("Cleaning up")
        for el in self.participants:
            el.cleanup()
        self.presence_message.deregister()
        self.eval_event = None
        self.initiator = None
        self.reg_start_time = None
        self.show_assignees = True
        self.reg_ts = None
        self.spoilered_users = []
        if exception:
            raise exception from exception
