"""
This subsystem provides listeners for direct messages (DMs) to the bot.
It is instantiated as `bot.dm_listener`.
"""

import logging

from base import BaseSubsystem
from botutils.utils import execute_anything


class Registration:
    """The registration which will be returned using `DMListener.register()`"""

    def __init__(self, listener, user, coro, kill_coro, name, data, blocking):
        self.listener = listener
        self.coro = coro
        self.kill_coro = kill_coro
        self.user = user
        self.data = data
        self.name = name
        self._blocking = blocking

        if self.kill_coro is None:
            logging.getLogger(__name__).warning("DM listener registered without kill_coro: %s. This is not advised.",
                                                self)

    def deregister(self):
        """Deregisters the DM listener registration"""
        self.listener.deregister(self)

    async def kill(self):
        """
        Forcefully deregisters this listener registration. This triggers the registrator's kill coro.
        """
        self.deregister()
        if self.kill_coro is not None:
            await execute_anything(self.kill_coro)

    @property
    def blocking(self):
        return self._blocking

    def __str__(self):
        return "<dmlisteners.Registration; name: {}; blocking: {}; coro: {}; user: {}>".format(
            self.name, self.blocking, self.coro, self.user)


class DMListener(BaseSubsystem):
    """The DM Listener Subsystem"""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.registrations = {}

    def register(self, user, coro, name, kill_coro=None, data=None, blocking=False):
        """
        Registers a listener on a direct message (DM) channel.

        :param user: User whose DM channel is observed.
        :param coro: Callback coroutine that is called as `await coro(registration, message)` with
            `registration` a Registration object, message a discord.Message object.
        :param name: String that identifies the source of the registration (e.g. command name).
        :param kill_coro: Coroutine that is called when this registration is killed. Use this to avoid memory leaks.
            Not passing this triggers a warning.
        :param data: Obaque object that will be part of the registration object.
        :param blocking: If this is set to True, sole access on the DM channel is claimed. No other listener will
            be able to be registered for this user's DM channel until this one is deregistered.
        :return: Registration object that can be used to deregister the listener.
        :raises RuntimeError: If there already is a blocking listener for `user`.
        :raises KeyError: If a blocking listener is to be registered but there already is a regular listener for `user`.
        """
        # find blocking violations
        for key in self.registrations:
            cb = self.registrations[key]
            if cb.user == user:
                if cb.blocking:
                    raise RuntimeError("A blocking DM listener for user {} is already registered.".format(user))
                if blocking:
                    raise KeyError("There is already a listener registered for user {}, unable to register "
                                   "blocking listener.".format(user))

        reg = Registration(self, user, coro, kill_coro, name, data, blocking)
        i = 1
        while True:
            if i not in self.registrations.keys():
                self.registrations[i] = reg
                break
            i += 1
        return reg

    def deregister(self, registration: Registration):
        """
        Removes a listener registration. Does nothing if the registration was not found.

        :param registration: Registration object that is to be unregistered
        """
        for key in self.registrations:
            if registration == self.registrations[key]:
                del self.registrations[key]
                break

    def is_registered(self, user) -> bool:
        """
        Checks if the User has registered DM listeners

        :param user: User to be checked
        :return: Returns whether there is a registered DM listener for `user`.
        """
        for key in self.registrations:
            if self.registrations[key].user == user:
                return True
        return False

    def is_blocked(self, user) -> bool:
        """
        Checks if the User has a blocking listener

        :param user: User to be checked
        :return: Returns True if there is a blocking listener for `user`, False otherwise.
        """
        for key in self.registrations:
            cb = self.registrations[key]
            if cb.blocking and user == cb.user:
                return True
        return False

    async def handle_dm(self, message) -> bool:
        """
        :param message: Message object
        :return: True if this was a blocking listener, False if not.
        """
        todo = []
        for key in self.registrations:
            cb = self.registrations[key]
            if cb.user == message.author:
                todo.append(cb)

        blocking = False
        for cb in todo:
            if cb.blocking:
                assert len(todo) == 1
                blocking = True
            await cb.coro(cb, message)
        return blocking
