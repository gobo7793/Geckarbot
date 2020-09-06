import logging
from enum import IntEnum
from typing import Optional

import discord

from base import BaseSubsystem
from conf import ConfigurableContainer, Config, Storage
from subsystems.timers import Job, timedict

"""
This subsystem provides changing presence messages for the user list on servers
"""


class PresencePriority(IntEnum):
    LOW = 0
    """
    Low priority for customized messages.
    Will be displayed on the same way as default prioritised by plugins.
    """

    DEFAULT = 1
    """
    Default priority for messages by plugins.
    Will be displayed if no high prioritised message is available.
    """

    HIGH = 2
    """
    High priority for special messages.
    High prioritised messages will be displayed the whole time while messages are registered.
    """


class Presence(BaseSubsystem):
    """Provides the presence subsystem"""

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger("presence")
        self.messages = {}

        self.log.info("Initializing presence subsystem")
        bot.plugins.append(ConfigurableContainer(self))
        self._load()

        self.timer_job = None  # type: Optional[Job]

        @bot.listen()
        async def on_connect():
            await self._set_presence(Storage.get(self)["loading"])

    def default_config(self):
        return {
            "update_period_min": 1
        }

    def default_storage(self):
        return {
            "loading": "Loading...",
            PresencePriority.LOW: [],
            PresencePriority.DEFAULT: [],
            PresencePriority.HIGH: []
        }

    def get_presence_messages_list(self):
        """Returns a list with all currently registered messages as tuple list with prio, index, msg"""
        messages = []

        for i in range(0, len(self.messages[PresencePriority.LOW])):
            messages.append((PresencePriority.LOW, i, self.messages[PresencePriority.LOW][i]))
        for i in range(0, len(self.messages[PresencePriority.DEFAULT])):
            messages.append((PresencePriority.DEFAULT, i, self.messages[PresencePriority.DEFAULT][i]))
        for i in range(0, len(self.messages[PresencePriority.HIGH])):
            messages.append((PresencePriority.HIGH, i, self.messages[PresencePriority.HIGH][i]))

        return messages

    def _load(self):
        """Loads the default messages for LOW priority only (!) from storage json."""
        Config.load(self)
        Storage.load(self)

        self.messages = self.default_storage()
        self.messages["loading"] = Storage.get(self)["loading"]
        self.messages[PresencePriority.LOW] = Storage.get(self)[PresencePriority.LOW]
        self.messages[PresencePriority.DEFAULT].append("Version {}".format(Config().VERSION))

        self.log.info("Loaded {} low prioritised messages".format(len(Storage.get(self)[PresencePriority.LOW])))

    def save(self):
        """Saves the current LOW priority (!) messages to json"""
        Storage.get(self)[PresencePriority.LOW] = self.messages[PresencePriority.LOW]

        Config.save(self)
        Storage.save(self)

    async def register(self, message, priority: PresencePriority = PresencePriority.DEFAULT):
        """
        Registers the given message to the given priority.
        Priority LOW is for customized messages which are unrelated from plugins or other bot functions.
        Priority DEFAULT is for messages provided by plugins e.g. displaying a current status.
        Priority HIGH is for special messages, which will be displayed instant and only if some are registered.

        :param message: The message
        :param priority: The priority
        :return: The message id for the registered message for the given priority (for deregistering)
        """
        new_id = len(self.messages[priority])
        self.messages[priority].append(message)
        self.save()

        self.log.debug("Message registered, Priority: {}, ID {}: {}".format(priority, new_id, message))

        if priority == PresencePriority.HIGH:
            await self._change_callback(self.timer_job)

        return new_id

    async def deregister(self, priority: PresencePriority, message_id: int):
        """
        Deregisters the message with the given id on the given priority and updates the displayed message if
        priority of the removed message was HIGH.

        :param priority: the priority
        :param message_id: the message id for the priority
        :return: True if message is deregistered or False if the message doesn't exist
        """
        if message_id < 0 or message_id >= len(self.messages[priority]):
            return False

        message = self.messages[priority][message_id]
        del (self.messages[priority][message_id])
        self.save()

        self.log.debug("Message deregistered, Priority: {}, ID {}: {}".format(priority, message_id, message))

        if priority == PresencePriority.HIGH:
            await self._change_callback(self.timer_job)

        return True

    async def start(self):
        """Starts the timer to change the presence messages periodically"""
        self.log.info("Start presence changing timer")
        time_dict = timedict(minute=[i for i in range(0, 60, Config.get(self)["update_period_min"])])
        self.timer_job = self.bot.timers.schedule(self._change_callback, time_dict, repeat=True)
        current_message = {
            "priority": PresencePriority.LOW,
            "msg_id": -1
        }
        self.timer_job.data = current_message
        await self._change_callback(self.timer_job)

    async def _set_presence(self, message):
        """Sets the presence message, based on discord.Game activity"""
        self.log.debug("Change displayed message to: {}".format(message))
        await self.bot.change_presence(activity=discord.Game(name=message))

    async def _change_callback(self, job):
        """The callback method for the timer subsystem to change the presence message"""

        old_prio = job.data["priority"]
        old_msg_id = job.data["msg_id"]

        if self.messages[PresencePriority.HIGH]:
            new_prio = PresencePriority.HIGH
            job.data["prio_before_high"] = old_prio
            job.data["msg_id_before_high"] = old_msg_id
        else:
            if old_prio == PresencePriority.HIGH:
                # make normal message change as if there was no high message
                new_prio = job.data["prio_before_high"]
                old_msg_id = job.data["msg_id_before_high"]
            else:
                new_prio = old_prio

        new_msg_id = old_msg_id + 1
        if new_msg_id >= len(self.messages[new_prio]) or old_prio != new_prio:
            new_msg_id = 0

        if new_msg_id == 0 and new_prio == PresencePriority.LOW and self.messages[PresencePriority.DEFAULT]:
            new_prio = PresencePriority.DEFAULT
        elif new_msg_id == 0 and new_prio == PresencePriority.DEFAULT and self.messages[PresencePriority.LOW]:
            new_prio = PresencePriority.LOW

        if new_prio == old_prio and new_msg_id == old_msg_id:
            return  # do nothing if the same message should be displayed again

        new_msg = self.messages[new_prio][new_msg_id]
        await self._set_presence(new_msg)

        job.data["priority"] = new_prio
        job.data["msg_id"] = new_msg_id
