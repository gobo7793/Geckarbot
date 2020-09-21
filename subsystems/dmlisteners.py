from base import BaseSubsystem

"""
This subsystem provides listeners for direct messages (DMs) to the bot.
It is instantiated as `bot.dm_listener`.
"""


class Registration:
    def __init__(self, listener, user, coro, data, blocking):
        self.listener = listener
        self.coro = coro
        self.user = user
        self.data = data
        self._blocking = blocking

    def deregister(self):
        self.listener.deregister(self)

    @property
    def blocking(self):
        return self._blocking

    def __str__(self):
        return "<dmlisteners.Registration; blocking: {}; coro: {}; user: {}>".format(self.blocking, self.coro, self.user)


class DMListener(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.registrations = []

    def register(self, user, coro, data=None, blocking=False):
        """
        Registers a listener on a direct message (DM) channel.
        :param user: User whose DM channel is observed.
        :param coro: Callback coroutine that is called as `await coro(registration, message)` with
        `registration` a Registration object, message a discord.Message object.
        :param data: Obaque object that will be part of the registration object.
        :param blocking: If this is set to True, sole access on the DM channel is claimed. No other listener will
        be able to be registered for this user's DM channel until this one is deregistered.
        :return: Registration object that can be used to deregister the listener.
        :raises: RuntimeError if there already is a blocking listener for `user`.
        :raises: KeyError if a blocking listener is to be registered but there already is a regular listener for `user`.
        """
        # find blocking violations
        for cb in self.registrations:
            if cb.user == user:
                if cb.blocking:
                    raise RuntimeError("A blocking DM listener for user {} is already registered.".format(user))
                elif blocking:
                    raise KeyError("There is already a listener registered for user {}, unable to register "
                                   "blocking listener.".format(user))

        reg = Registration(self, user, coro, data, blocking)
        self.registrations.append(reg)
        return reg

    def deregister(self, registration):
        """
        Removes a listener registration. Does nothing if the registration was not found.
        :param registration: Registration object that is to be unregistered
        """
        if registration in self.registrations:
            self.registrations.remove(registration)

    def is_registered(self, user):
        """
        :param user: User to be checked
        :return: Returns whether there is a registered DM listener for `user`.
        """
        for cb in self.registrations:
            if cb.user == user:
                return True
        return False

    def is_blocked(self, user):
        """
        :param user: User to be checked
        :return: Returns True if there is a blocking listener for `user`, False otherwise.
        """
        for cb in self.registrations:
            if cb.blocking and user == cb.user:
                return True
        return False

    async def handle_dm(self, message):
        """
        :param message: Message object
        :return: True if this was a blocking listener, False if not.
        """
        todo = []
        for cb in self.registrations:
            if cb.user == message.author:
                todo.append(cb)

        blocking = False
        for cb in todo:
            if cb.blocking:
                assert len(todo) == 1
                blocking = True
            await cb.coro(cb, message)
        return blocking
