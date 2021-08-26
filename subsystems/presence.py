"""
This subsystem provides changing presence messages for the user list on servers
"""

import asyncio
import logging
import random
from enum import IntEnum
from typing import Optional, List, Dict

import discord

from base import BaseSubsystem, NotFound
from data import Config, Storage
from botutils.utils import log_exception
from subsystems.timers import Job, timedict


activitymap = {
    "playing": discord.ActivityType.playing,
    # "streaming": discord.ActivityType.streaming,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
    # "custom": discord.ActivityType.custom,
}


class SkipPresence(Exception):
    """
    To be raised by PresenceMessage.set implementations if the presence message is to be skipped instead of set.
    """
    pass


class PresencePriority(IntEnum):
    """Priority enumeration for presence messages"""

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

    def __init__(self, bot, presence_id: Optional[int], message: str,
                 priority: PresencePriority = PresencePriority.DEFAULT, activity: str = "playing"):
        """
        Creates a new PresenceMessage

        :param bot: The bot reference
        :param presence_id: the unique presence message id. If set to None, one is determined automatically.
        :param message: the message to display
        :param priority: the priority of the message
        :param activity: presence mode (listening, playing, ...); one out of activitymap
        :raises RuntimeError: Invalid activity
        """
        self.bot = bot
        if presence_id is not None:
            self.presence_id = presence_id
        else:
            self.presence_id = self.bot.presence.get_new_id()
        self._activity_str = activity
        self.priority = priority

        message = message.replace("\\\\\\", "\\")
        message = message.replace("\\\\", "\\")
        self.message = message

        try:
            self._activity = activitymap[self._activity_str]
        except KeyError as e:
            raise RuntimeError("Invalid activity type: {}".format(self._activity_str)) from e
        self._activity = discord.Activity(type=self._activity, name=message)

    def __str__(self):
        return "<presence.PresenceMessage; priority: {}, id: {}, message: {}>".format(
            self.priority, self.presence_id, self.message)

    @property
    def activity(self):
        return self._activity_str

    @property
    def activity_type(self):
        return self._activity

    async def set(self):
        """
        Is called when this presence message is set. This method is expected to set the bot's presence.
        """
        self.bot.presence.log.debug("Change displayed message to: %s", self.message)
        await self.bot.change_presence(activity=self.activity_type)

    async def unset(self):
        """
        Called when this message is being un-set (aka the next msg is set).
        """
        pass

    def serialize(self) -> dict:
        """
        :return: A dict with the keys id, message, priority
        """
        return {
            "id": self.presence_id,
            "activity": self.activity,
            "message": self.message,
            "priority": self.priority,
        }

    @classmethod
    def deserialize(cls, bot, d):
        """
        Constructs a PressenceMessage object from a dict.

        :param bot: The bot reference
        :type bot: Geckarbot.Geckarbot
        :param d: dict made by serialize()
        :type d: dict
        :return: PressenceMessage object
        :rtype: PresenceMessage
        """
        activity = "playing"
        if "activity" in d:
            for key in activitymap:
                if d["activity"] == key:
                    activity = d["activity"]

        return PresenceMessage(bot, d["id"], d["message"], priority=d["priority"], activity=activity)

    def deregister(self):
        """Deregisters the current PresenceMessage and returns True if deregistering was successful"""
        return self.bot.presence.deregister(self)


class Presence(BaseSubsystem):
    """Provides the presence subsystem"""

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)
        self.messages = {}  # type: Dict[int, PresenceMessage]
        self.highest_id = None  # type: Optional[int]
        self._timer_job = None  # type: Optional[Job]

        self.log.info("Initializing presence subsystem")
        bot.plugins.append(self)
        self._load()

        # pylint: disable=unused-variable
        @bot.listen()
        async def on_connect():
            if bot.DEBUG_MODE:
                activity = discord.Activity(type=activitymap["playing"], name="in debug mode")
            else:
                activity = discord.Activity(type=activitymap["playing"], name=Config.get(self)["loading_msg"])
            await self.bot.change_presence(activity=activity)

    def default_config(self, container=None):
        return {
            "update_period_min": 10,
            "loading_msg": "Loading..."
        }

    def default_storage(self, container=None):
        if container:
            raise NotFound
        return []

    @property
    def is_timer_up(self):
        return self._timer_job is not None and not self._timer_job.cancelled

    def get_new_id(self) -> int:
        """
        Acquires a new presence message id

        :return: free unique id that can be used for a new presence message
        """
        return max(self.messages) + 1

    def get_next_id(self, start_id: int, priority: PresencePriority = None) -> int:
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

    def get_ran_id(self, excluded_id: int, priority: PresencePriority = None) -> int:
        """
        Returns a random existing unique presence message ID, excluding the excluded_id
        If the given ID is the last existing ID, the first ID will be returned.
        If no message is registered, -1 will be returned.

        :param excluded_id: the excluded id
        :param priority: If given, returns only IDs of messages with given priority
        :return: The next registered unique ID
        """
        if not self.messages:
            return -1

        message_list = list(self.messages.values()) if priority is None else self.filter_messages_list(priority)
        if len(message_list) < 1:
            return 0
        if len(message_list) == 1:
            return message_list[0].presence_id

        while True:
            select = random.choice(message_list)
            if select.presence_id != excluded_id:
                return select.presence_id

    def filter_messages_list(self, priority: PresencePriority) -> List[PresenceMessage]:
        """Returns all messages with the given priority"""
        return [msg for msg in self.messages.values() if msg.priority == priority]

    def _load(self):
        """Resets the messages and loads the config and messages from json."""
        Config.load(self)
        Storage.load(self)

        self.messages = {}
        self.highest_id = None

        self.messages[0] = PresenceMessage(self.bot, 0, "Version {}".format(self.bot.VERSION))
        for el in Storage.get(self):
            presence_msg = PresenceMessage.deserialize(self.bot, el)
            self.messages[presence_msg.presence_id] = presence_msg

        self.log.info("Loaded %d messages", len(self.messages))

    def save(self):
        """Saves the current LOW priority (!) messages to json"""
        to_save = []
        for el in self.filter_messages_list(PresencePriority.LOW):
            to_save.append(el.serialize())

        Storage.set(self, to_save)

        Config.save(self)
        Storage.save(self)

    def register(self, message: str, activity: str = "playing",
                 priority: PresencePriority = PresencePriority.DEFAULT) -> PresenceMessage:
        """
        Registers the given message to the given priority.
        Priority LOW is for customized messages which are unrelated from plugins or other bot functions.
        Priority DEFAULT is for messages provided by plugins e.g. displaying a current status.
        Priority HIGH is for special messages, which will be displayed instantly and only if some are registered.

        :param message: The message content
        :param activity: The activity type as a string (such as `"playing"`, "`listening`" etc)
        :param priority: The priority
        :return: The PresenceMessage dataset object of the new registered presence message
        """
        presence = PresenceMessage(self.bot, None, message, priority=priority, activity=activity)
        self.register_msg(presence)
        return presence

    def register_msg(self, presence_msg: PresenceMessage):
        """
        Registers the given PresenceMessage object as a presence.

        :param presence_msg: PresenceMessage
        """
        self.messages[presence_msg.presence_id] = presence_msg

        self.save()

        self.log.debug("Message registered, Priority: %s, ID %d: %s",
                       presence_msg.priority, presence_msg.presence_id, presence_msg.message)

        if presence_msg.priority == PresencePriority.HIGH:
            self.execute_change()

    def deregister_id(self, message_id: int) -> bool:
        """
        Deregisters the presence message with the given id and updates the displayed message if
        priority of the removed message was HIGH.

        :param message_id: the unique id of the presence message
        :return: True if the message with the id was deregistered or False if a message with the id doesn't exist
        """
        if message_id not in self.messages:
            return False
        return self.deregister(self.messages[message_id])

    def deregister(self, dataset: PresenceMessage) -> bool:
        """
        Deregisters the given PresenceMessage dataset and updates the displayed message if
        priority of the removed message was HIGH.

        :param dataset: The PresenceMessage dataset to deregister
        :return: True if PresenceMessage dataset was deregistered or False if the dataset isn't registered
        """
        if dataset.presence_id not in self.messages:
            return False

        del self.messages[dataset.presence_id]
        self.save()
        self.log.debug("Message deregistered, Priority: %s, ID %d: %s",
                       dataset.priority, dataset.presence_id, dataset.message)

        self._execute_removing_change(dataset.presence_id)

        return True

    async def start(self):
        """Starts the timer to change the presence messages periodically"""
        if self.is_timer_up:
            self.log.warning("Timer job already started. This call shouldn't happen.")
            return

        self.log.info("Start presence changing timer")
        time_dict = timedict(minute=list(range(0, 60, Config.get(self)["update_period_min"])))
        self._timer_job = self.bot.timers.schedule(self._change_callback, time_dict, repeat=True)
        job_data = {
            "current_id": -1,
            "current_msg": None,
            "last_prio": PresencePriority.DEFAULT,
            "id_before_high": -1,
        }
        self._timer_job.data = job_data
        await self._change_callback(self._timer_job)

    def stop(self):
        """Stops the timer to change the presence messsage"""
        self._timer_job.cancel()
        self._timer_job = None

    async def skip(self):
        """
        Skips the current presence (moves on).

        :raises RuntimeError: If presence timer is not up.
        """
        if not self.is_timer_up:
            raise RuntimeError
        await self._change_callback(self._timer_job)

    def _execute_removing_change(self, removed_id: int):
        """Executes _change_callback() w/o awaiting with special handling for removed presence messages"""
        if self.is_timer_up and (self._timer_job.data["last_prio"] == PresencePriority.HIGH
                                 or self._timer_job.data["current_id"] == removed_id):
            self.execute_change()

    def execute_change(self):
        """Executes _change_callback() w/o awaiting (every time this method is called)"""
        if self.is_timer_up:
            asyncio.run_coroutine_threadsafe(self._change_callback(self._timer_job), self.bot.loop)

    async def _change_callback(self, job):
        """
        The callback method for the timer subsystem to change the presence message.
        Sets a presence with the following conditions:
            1. Prio as high as possible
            2. Not the same presence as before (if possible within the prio list)
            3. Randomly chosen
            4. If the presence message raises SkipPresence, tries again
        """
        self.log.debug("Executing presence change callback")
        prio = None
        if len(self.filter_messages_list(PresencePriority.HIGH)) > 0:
            prio = PresencePriority.HIGH

        # Search for new presence msg
        error = None
        while True:
            last_id = job.data["current_id"]
            next_id = self.get_ran_id(last_id, priority=prio)
            if next_id == last_id:
                return  # do nothing if the same message should be displayed again

            new_msg = self.messages[next_id]
            try:
                await new_msg.set()
            except SkipPresence:
                self.log.debug("%s raised SkipPresence; skipping", new_msg)
                continue
            except Exception as e:
                error = e
            break

        if error:
            await log_exception(error, title=":x: Presence set error")

        to_unset = job.data["current_msg"]
        job.data["current_id"] = next_id
        job.data["current_msg"] = new_msg

        if to_unset:
            await to_unset.unset()
