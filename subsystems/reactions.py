from enum import Enum


class BaseReactionEvent:
    def __init__(self, callback, data, user, member, channel, message, emoji):
        self.callback = callback
        self.data = data
        self.user = user
        self.member = member
        self.channel = channel
        self.message = message
        self.emoji = emoji


class ReactionRemovedEvent(BaseReactionEvent):
    pass


class ReactionAddedEvent(BaseReactionEvent):
    pass


class ReactionAction(Enum):
    ADD = 0
    REMOVE = 1


async def build_reaction_event(bot, callback, payload, data, action, message=None):
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


class Callback:
    def __init__(self, listener, msg, coro, data):
        self.listener = listener
        self.message = msg
        self.coro = coro
        self.data = data

    def unregister(self):
        self.listener.unregister(self)

    def __str__(self):
        return "<reactions.Callback; coro: {}; msg: {}>".format(self.coro, self.message)


class ReactionListener:
    def __init__(self, bot):
        self.callbacks = []
        self.bot = bot
        self.to_del = []
        self._checking = False

        @bot.listen()
        async def on_raw_reaction_add(payload):
            await self.check(payload, ReactionAction.ADD)

        @bot.listen()
        async def on_raw_reaction_remove(payload):
            await self.check(payload, ReactionAction.REMOVE)

    async def check(self, payload, action: ReactionAction):
        for el in self.to_del:
            if el in self.callbacks:
                self.callbacks.remove(el)
        self.to_del = []

        self._checking = True
        found = []
        for el in self.callbacks:
            if el.message.id == payload.message_id:
                found.append(el)

        if found:
            for el in found:
                event = await build_reaction_event(self.bot, el, payload, el.data, action)
                await el.coro(event)

        self._checking = False

    def register(self, message, coro, data=None):
        """
        Registers a reaction event listener.
        :param message: Message that is observed
        :param coro: Callback coroutine that is called as await coro(event).
        :param data: Obaque object that will be part of the event object as event.data.
        :return: Callback object that can be used to unregister the listener.
        """
        cb = Callback(self, message, coro, data)
        self.callbacks.append(cb)
        return cb

    def unregister(self, callback):
        if self._checking:
            self.to_del.append(callback)
        else:
            if callback in self.callbacks:
                self.callbacks.remove(callback)
