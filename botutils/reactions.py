from enum import Enum


class BaseReactionEvent:
    def __init__(self, user, member, channel, message, emoji):
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


async def build_reaction_event(bot, payload, action, message=None):
    # Figure out event class
    eventclass = None
    if action == ReactionAction.ADD:
        eventclass = ReactionAddedEvent
    elif action == ReactionAction.REMOVE:
        eventclass = ReactionRemovedEvent
    else:
        assert False

    # Get objects from IDs
    user = bot.guild.get_member(payload.user_id)
    member = bot.get_user(payload.user_id)
    channel = bot.get_channel(payload.channel_id)
    if message is None:
        message = await channel.fetch_message(payload.message_id)
    return eventclass(user, member, channel, message, payload.emoji)


class Callback:
    def __init__(self, msg, f, *args, **kwargs):
        self.msg = msg
        self.function = f
        self.args = args
        self.kwargs = kwargs


class ReactionListener:
    def __init__(self, bot):
        self.callbacks = []
        self.bot = bot

        @bot.listen()
        async def on_raw_reaction_add(payload):
            await self.check(payload, ReactionAction.ADD)

        @bot.listen()
        async def on_raw_reaction_remove(payload):
            await self.check(payload, ReactionAction.REMOVE)

    async def check(self, payload, action: ReactionAction):
        found = []
        for el in self.callbacks:
            msg, _ = el
            if msg.id == payload.message_id:
                found.append(el)

        if found:
            event = await build_reaction_event(self.bot, payload, action)
            for _, coro in found:
                await coro(event)

    def register(self, message, coro):
        """
        Registers a reaction event listener.
        :param message: Message that is observed
        :param coro: Callback coroutine that is called as await coro(event).
        :return:
        """
        self.callbacks.append((message, coro))
