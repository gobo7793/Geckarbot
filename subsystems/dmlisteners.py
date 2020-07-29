"""
This subsystem provides listeners for direct messages (DMs) to the bot.
"""


class Callback:
    def __init__(self, listener, user, coro, data, blocking):
        self.listener = listener
        self.coro = coro
        self.user = user
        self.data = data
        self._blocking = blocking

    def unregister(self):
        self.listener.unregister(self)

    @property
    def blocking(self):
        return self._blocking

    def __str__(self):
        return "<dmlisteners.Callback; blocking: {}; coro: {}; user: {}>".format(self.blocking, self.coro, self.user)


class DMListener:
    def __init__(self, bot):
        self.bot = bot
        self.callbacks = []

    def register(self, user, coro, data=None, blocking=False):
        """
        Registers a listener on a direct message (DM) channel.
        :param user: User whose DM channel is observed.
        :param coro: Callback coroutine that is called as await coro(callback, message) with
        `callback` a Callback object, message a discord.Message object.
        :param data: Obaque object that will be part of the callback object.
        :param blocking: If this is set to True, sole access on the DM channel is claimed. No other listener will
        be able to be registered for this user's DM channel until this one is unregistered.
        :return: Callback object that can be used to unregister the listener.
        """
        # find blocking violations
        for cb in self.callbacks:
            if cb.user == user:
                if cb.blocking:
                    raise RuntimeError("A blocking DM listener for user {} is already registered.".format(user))
                elif blocking:
                    raise KeyError("There is already a listener registered for user {}, unable to register "
                                   "blocking listener.".format(user))

        cb = Callback(self, user, coro, data, blocking)
        self.callbacks.append(cb)
        return cb

    def unregister(self, callback):
        """
        Removes a listener registration. Does nothing if the registration was not found.
        :param callback: Callback object that is to be unregistered
        """
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def is_registered(self, user):
        """
        :param user: User to be checked
        :return: Returns whether there is a registered DM listener for `user`.
        """
        for cb in self.callbacks:
            if cb.user == user:
                return True
        return False

    def is_blocked(self, user):
        """
        :param user: User to be checked
        :return: Returns True if there is a blocking listener for `user`, False otherwise.
        """
        for cb in self.callbacks:
            if cb.blocking and user == cb.user:
                return True
        return False

    async def handle_dm(self, message):
        """
        :param message: Message object
        :return: True if this was a blocking listener, False if not.
        """
        todo = []
        for cb in self.callbacks:
            if cb.user == message.author:
                todo.append(cb)

        blocking = False
        for cb in todo:
            if cb.blocking:
                assert len(todo) == 1
                blocking = True
            await cb.coro(cb, message)
        return blocking
