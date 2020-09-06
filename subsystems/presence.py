import asyncio
import logging
from enum import IntEnum
from typing import Optional, List, Dict

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


class PresenceMessage:
    """Presence message dataset"""

    def __init__(self, bot, presence_id: int, message: str, priority: PresencePriority = PresencePriority.DEFAULT):
        """
        Creates a new PresenceMessage

        :param bot: The bot reference
        :param presence_id: the unique presence message id
        :param message: the message to display
        :param priority: the priority of the message
        """
        self.bot = bot
        self.presence_id = presence_id
        self.priority = priority
        self.message = message

    def __str__(self):
        return "<presence.PresenceMessage; priority: {}, id: {}, message: {}>".format(
            self.priority, self.presence_id, self.message)

    def serialize(self):
        """
        :return: A dict with the keys id, message, priority
        """
        return {
            "id": self.presence_id,
            "message": self.message,
            "priority": self.priority,
        }

    @classmethod
    def deserialize(cls, bot, d):
        """
        Constructs a PressenceMessage object from a dict.

        :param bot: The bot reference
        :param d: dict made by serialize()
        :return: PressenceMessage object
        """
        return PresenceMessage(bot, d["id"], d["message"], d["priority"])

    def deregister(self):
        """Deregisters the current PresenceMessage and returns True if deregistering was successful"""
        return self.bot.presence.deregister(self)


class Presence(BaseSubsystem):
    """Provides the presence subsystem"""

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger("presence")
        self.messages = {}  # type: Dict[int]
        self.highest_id = None  # type: Optional[int]
        self.timer_job = None  # type: Optional[Job]

        self.log.info("Initializing presence subsystem")
        bot.plugins.append(ConfigurableContainer(self))
        self._load()

        @bot.listen()
        async def on_connect():
            await self._set_presence(Config.get(self)["loading_msg"])

    def default_config(self):
        return {
            "update_period_min": 3,
            "loading_msg": "Loading..."
        }

    def default_storage(self):
        return []

    def get_new_id(self, init=False):
        """
        Acquires a new presence message id

        :param init: if True, only sets self.highest_id but does not return anything. Useful for init.
        :return: free unique id that can be used for a new presence message
        """
        if self.highest_id is None:
            self.highest_id = max(self.messages)

        if not init:
            self.highest_id += 1
            return self.highest_id

    def get_next_id(self, start_id: int, priority: PresencePriority = None):
        """
        Returns the next existing unique presence message ID starting on the given id.
        If the given ID is the last existing ID, the first ID will be returned.
        If no message is registered, -1 will be returned.

        :param start_id: the ID to start the search
        :param priority: If given, returns only IDs of messages with given priority
        :return: The next registered unique ID
        """
        if not self.messages:
            return -1

        current_id = start_id
        while True:
            current_id += 1
            if current_id in self.messages:
                if priority is None or priority == self.messages[current_id].priority:
                    return current_id
            if current_id > self.highest_id:
                current_id = -1

    def filter_messages_list(self, priority: PresencePriority) -> List[PresenceMessage]:
        """Returns all messages with the given priority"""
        return [msg for msg in self.messages.values() if msg.priority == priority]

    def _load(self):
        """Resets the messages and loads the config and messages from json."""
        Config.load(self)
        Storage.load(self)

        self.messages = {}
        self.highest_id = None

        self.messages[0] = PresenceMessage(self.bot, 0, "Version {}".format(Config().VERSION))
        for el in Storage.get(self):
            presence_msg = PresenceMessage.deserialize(self.bot, el)
            self.messages[presence_msg.presence_id] = presence_msg

        self.get_new_id(init=True)

        self.log.info("Loaded {} messages".format(len(self.messages)))

    def save(self):
        """Saves the current LOW priority (!) messages to json"""
        to_save = []
        for el in self.filter_messages_list(PresencePriority.LOW):
            to_save.append(el.serialize())

        Storage.set(self, to_save)

        Config.save(self)
        Storage.save(self)

    def register(self, message, priority: PresencePriority = PresencePriority.DEFAULT):
        """
        Registers the given message to the given priority.
        Priority LOW is for customized messages which are unrelated from plugins or other bot functions.
        Priority DEFAULT is for messages provided by plugins e.g. displaying a current status.
        Priority HIGH is for special messages, which will be displayed instant and only if some are registered.

        :param message: The message
        :param priority: The priority
        :return: The PresenceMessage dataset object of the new registered presence message
        """
        new_id = self.get_new_id()
        presence = PresenceMessage(self.bot, new_id, message, priority)
        self.messages[new_id] = presence

        self.save()

        self.log.debug("Message registered, Priority: {}, ID {}: {}".format(priority, new_id, message))

        if priority == PresencePriority.HIGH:
            self._execute_change()

        return presence

    def deregister_id(self, message_id: int):
        """
        Deregisters the presence message with the given id and updates the displayed message if
        priority of the removed message was HIGH.

        :param message_id: the unique id of the presence message
        :return: True if the message with the id was deregistered or False if a message with the id doesn't exist
        """
        if message_id not in self.messages:
            return False
        return self.deregister(self.messages[message_id])

    def deregister(self, dataset: PresenceMessage):
        """
        Deregisters the given PresenceMessage dataset and updates the displayed message if
        priority of the removed message was HIGH.

        :param dataset: The PresenceMessage dataset to deregister
        :return: True if PresenceMessage dataset was deregistered or False if the dataset isn't registered
        """
        if dataset.presence_id not in self.messages:
            return False

        del(self.messages[dataset.presence_id])
        self.save()
        self.log.debug("Message deregistered, Priority: {}, ID {}: {}".format(
            dataset.priority, dataset.presence_id, dataset.message))

        if dataset.priority == PresencePriority.HIGH:
            self._execute_change()

        return True

    async def start(self):
        """Starts the timer to change the presence messages periodically"""
        if self.timer_job is not None:
            self.log.warning("Timer job already started. This call shouldn't happen.")
            return

        self.log.info("Start presence changing timer")
        time_dict = timedict(minute=[i for i in range(0, 60, Config.get(self)["update_period_min"])])
        self.timer_job = self.bot.timers.schedule(self._change_callback, time_dict, repeat=True)
        job_data = {
            "current_id": -1,
            "last_prio": PresencePriority.DEFAULT,
            "id_before_high": -1
        }
        self.timer_job.data = job_data
        await self._change_callback(self.timer_job)

    async def _set_presence(self, message):
        """Sets the presence message, based on discord.Game activity"""
        self.log.debug("Change displayed message to: {}".format(message))
        await self.bot.change_presence(activity=discord.Game(name=message))

    def _execute_change(self):
        """Executes _change_callback() w/o awaiting"""
        asyncio.run_coroutine_threadsafe(self._change_callback(self.timer_job), self.bot.loop)

    async def _change_callback(self, job):
        """The callback method for the timer subsystem to change the presence message"""

        last_id = job.data["current_id"]
        high_list = self.filter_messages_list(PresencePriority.HIGH)

        if len(high_list) > 0:
            next_prio = PresencePriority.HIGH
        else:
            next_prio = None
            if job.data["last_prio"] == PresencePriority.HIGH:
                last_id = job.data["id_before_high"] - 1  # restore last message before high

        next_id = self.get_next_id(last_id, next_prio)

        if next_id == last_id:
            return  # do nothing if the same message should be displayed again

        job.data["id_before_high"] = last_id
        new_msg = self.messages[next_id]
        await self._set_presence(new_msg.message)

        job.data["last_prio"] = new_msg.priority
        job.data["current_id"] = next_id
