"""
This subsystem provides listeners for reactions on messages.
"""

from enum import Enum
from typing import Union, Coroutine, Callable

from nextcord import Message

from base.configurable import BaseSubsystem
from base.data import Config
from botutils.utils import log_exception


class BaseReactionEvent:
    """The object that carries information about the reaction event."""

    def __init__(self, callback, data, user, member, channel, message, emoji):
        self.callback = callback
        """A reference to the callback coroutine."""
        self.data = data
        """Opaque object that the user specified in the registration process."""
        self.user = user
        """User that did the reaction."""
        self.member = member
        """Member that did the reaction. If the user is not a member, this is None."""
        self.channel = channel
        """The channel of the message."""
        self.message = message
        """Message that the reaction was added or removed on."""
        self.emoji = emoji
        """ The reaction emoji."""


class ReactionRemovedEvent(BaseReactionEvent):
    """Event data after a reaction was removed from a message."""


class ReactionAddedEvent(BaseReactionEvent):
    """Event data after a reaction was added to a message."""


class ReactionAction(Enum):
    """The action type of the reaction event"""
    ADD = 0
    REMOVE = 1


async def _build_reaction_event(bot, callback, payload, data, action, message=None) -> BaseReactionEvent:
    # Figure out event class
    if action == ReactionAction.ADD:
        eventclass = ReactionAddedEvent
    elif action == ReactionAction.REMOVE:
        eventclass = ReactionRemovedEvent
    else:
        assert False

    # Get objects from IDs
    member = bot.guild.get_member(payload.user_id)
    user = bot.get_user(payload.user_id)
    channel = bot.get_channel(payload.channel_id)
    if message is None:
        message = await channel.fetch_message(payload.message_id)
    return eventclass(callback, data, user, member, channel, message, payload.emoji)


class Registration:
    """The callback which represents a reaction listener registration"""
    def __init__(self, listener, msg, coro, data):
        self.listener = listener
        self.message = msg
        self.coro = coro
        self.data = data

    def deregister(self):
        """Deregisters the reaction listener"""
        self.listener.deregister(self)

    async def execute(self, event):
        try:
            await self.coro(event)
        # pylint: disable=broad-except
        except Exception as e:
            fields = {"Coroutine": str(self.coro), "Event": event}
            await log_exception(e, title=":x: Reaction Listener Error", fields=fields)

    def __str__(self):
        return "<reactions.Callback; coro: {}; msg: {}>".format(self.coro, self.message)


class ReactionListener(BaseSubsystem):
    """Reaction listener subsystem"""
    def __init__(self):
        super().__init__()
        self.registrations = []
        self.bot = Config().bot
        self.to_del = []
        self._checking = False

        # pylint: disable=unused-variable
        @self.bot.listen()
        async def on_raw_reaction_add(payload):
            await self._check(payload, ReactionAction.ADD)

        @self.bot.listen()
        async def on_raw_reaction_remove(payload):
            await self._check(payload, ReactionAction.REMOVE)

    async def _check(self, payload, action: ReactionAction):
        for el in self.to_del:
            if el in self.registrations:
                self.registrations.remove(el)
        self.to_del = []

        self._checking = True
        found = []
        for el in self.registrations:
            if el.message.id == payload.message_id:
                found.append(el)

        if found:
            for el in found:
                event = await _build_reaction_event(self.bot, el, payload, el.data, action)
                await el.execute(event)

        self._checking = False

    def register(self, message: Message, coro: Union[Coroutine, Callable], data=None) -> Registration:
        """
        Registers a reaction event listener.

        :param message: Message that is observed
        :param coro: Callback coroutine that is called as await coro(event).
        :param data: Obaque object that will be part of the event object as event.data.
        :return: Callback object that can be used to unregister the listener.
        """
        reg = Registration(self, message, coro, data)
        self.registrations.append(reg)
        return reg

    def deregister(self, registration):
        """
        Deregisters the reaction listener for the given callback

        :param registration: The registration object that was returned by register()
        """
        if self._checking:
            self.to_del.append(registration)
        else:
            if registration in self.registrations:
                self.registrations.remove(registration)
