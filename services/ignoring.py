"""
This subsystem provides the possibility to block certain commands, users or active and passive command usage.
"""

import enum
import logging
from datetime import datetime

import discord
from discord.ext import commands
from discord.ext.commands import DisabledCommand

from base.configurable import BaseSubsystem
from data import Storage, Lang, Config
from botutils import utils
from botutils.converters import get_best_username, get_best_user
from services import timers


class UserBlockedCommand(DisabledCommand):
    """
    Will be raised if a command is blocked for the specific user.
    Can be used for passive command checking.
    """

    def __init__(self, user: discord.abc.User, command: str = ""):
        self.user = user
        self.command = command
        super().__init__()


class IgnoreType(enum.IntEnum):
    """The possible types for ignore list entries."""

    NA = 0
    """
    Not defined
    """

    USER = 1
    """
    Blocks any interactions between user and bot.
    Disables command_name and channel arguments in IgnoreDataset.
    """

    COMMAND = 2
    """
    Disables command usage in specific channel.
    Disables user argument in IgnoreDataset.
    """

    PASSIVE_USAGE = 3
    """
    Blocks any active and passive usage of the command for a specific user.
    Disables channel argument in IgnoreDataset.
    """

    ACTIVE_USAGE = 4
    """
    Blocks any active (not passive) usage of the command for a specific user.
    Disables channel argument in IgnoreDataset.
    """


class IgnoreEditResult(enum.Enum):
    """Return codes for adding and removing datasets to ignore list."""

    SUCCESS = 0
    """Successfully added/removed to ignore list"""
    ALREADY_IN_LIST = 1
    """Dataset is already in list."""
    NOT_IN_LIST = 2
    """Dataset is not in list."""
    UNTIL_IN_PAST = 3
    """Until datetime for auto-remove is in past, dataset was not added to ignore list."""


class IgnoreDataset:
    """
    The ignoring dataset.
    Supports equal operation and checks equality based on type, user id, command name and channel id.
    """

    def __init__(self, ignore_type: IgnoreType, user: discord.User = None, command_name: str = "",
                 channel: discord.TextChannel = None, until: datetime = datetime.max, job: timers.Job = None,
                 ignoring_instance=None):
        """
        Creates a new ignoring dataset.
        Not needed args can be None, eg for ignoring user completely the args command_name and channel.
        Disabled arguments based on type raises ValueError.

        :param ignore_type: The type of the ignore dataset, defines not possible arguments
        :param user: The user to ignore.
            For IgnoreType.User, IgnoreType.Passive_Usage and IgnoreType.Active_Usage.
        :param command_name: The command name to disabling for active/passive usage or completely in a channel.
            For IgnoreType.User, IgnoreType.Passive_Usage and IgnoreType.Active_Usage.
        :param channel: The channel in which a command is disabled. For IgnoreType.Command.
        :param until: The datetime on which the ignoring entry will be auto-removed. Possible for all types.
        :param job: The timer subsystem job for auto-remove
        :param ignoring_instance: The instance of the ignoring subsystem. Only necessary for to_message().
        :type ignoring_instance: Ignoring

        :raises ValueError: If ignore_type and given parameter don't fit
        """
        if (ignore_type == IgnoreType.USER
                and (user is None
                     or command_name
                     or channel is not None)):
            raise ValueError("User blocking accepts the user argument only.")
        if (ignore_type == IgnoreType.COMMAND
                and (user is not None
                     or not command_name
                     or channel is None)):
            raise ValueError("Command disabling needs both of command_name and channel arguments only.")
        if (ignore_type == IgnoreType.PASSIVE_USAGE
                and (user is None
                     or not command_name
                     or channel is not None)):
            raise ValueError("Blocking active and passive usage needs both of user and command_name arguments only.")
        if (ignore_type == IgnoreType.ACTIVE_USAGE
                and (user is None
                     or not command_name
                     or channel is not None)):
            raise ValueError("Blocking active usage needs both of user and command_name arguments only.")

        self.ignore_type = ignore_type
        self.user = user
        self.command_name = command_name
        self.channel = channel
        self.until = until
        self.job = job
        self.ignoring_instance = ignoring_instance

    def __eq__(self, other):
        if isinstance(other, IgnoreDataset):
            type_res = self.ignore_type == other.ignore_type
            user_res = IgnoreDataset._eq(self.user, other.user)
            cmd_res = str(self.command_name) == str(other.command_name)
            chan_res = IgnoreDataset._eq(self.channel, other.channel)

            return type_res and user_res and cmd_res and chan_res
        return False

    @classmethod
    def _eq(cls, self, other):
        """__eq__ helper method"""
        if self is not None and other is not None:
            return self == other
        return self is None and other is None

    def __str__(self):
        return "<ignoring.IgnoreDataset; {}, user: {}, command: {}, channel: {}, until: {}>".format(
            str(IgnoreType(self.ignore_type)), self.user, self.command_name, self.channel, self.until)

    def serialize(self) -> dict:
        """
        Serializes the dataset to a dict

        :return: A dict with the keys user_id, command_name, channel_id, until
        """
        user_id = 0
        channel_id = 0
        if self.user is not None:
            user_id = self.user.id
        if self.channel is not None:
            channel_id = self.channel.id

        return {
            "type": self.ignore_type,
            "userid": user_id,
            "command_name": self.command_name,
            "channelid": channel_id,
            "until": self.until
        }

    @classmethod
    def deserialize(cls, bot, d, ignoring_instance=None):
        """
        Constructs a IgnoreDataset object from a dict.

        :param bot: Geckarbot reference
        :type bot: Geckarbot.Geckarbot
        :param d: dict made by serialize()
        :type d: dict
        :param ignoring_instance: The ignoring subsystem instance, only necessary for to_message()
        :type ignoring_instance: Ignoring
        :return: IgnoreDataset object
        :rtype: IgnoreDataset
        """
        user = get_best_user(d["userid"])
        channel = bot.get_channel(d["channelid"])
        return IgnoreDataset(d["type"], user, d["command_name"], channel, d["until"],
                             ignoring_instance=ignoring_instance)

    def to_message(self) -> str:
        """
        Builds an well formatted output message for listing the entries on ignore list.

        Format for User or User_Command IgnoreType:
            User user_name will be ignored [for command command_name] until.../forever.
        Format for Command IgnoreType:
            Command command_name is disabled in channel channel_name until.../forever.

        For other IgnoreTypes, the raw message will be returned.

        :return: The well formatted message
        """

        if self.ignoring_instance is None:
            return str(self)

        dt = ""
        if self.until < datetime.max:
            dt = Lang.lang(self.ignoring_instance, 'until',
                           self.until.strftime(Lang.lang(self.ignoring_instance, 'until_strf')))

        if self.ignore_type == IgnoreType.USER:
            m = Lang.lang(self.ignoring_instance, 'user_ignore_msg', self.user.display_name, dt)

        elif self.ignore_type == IgnoreType.COMMAND:
            m = Lang.lang(self.ignoring_instance, 'cmd_ignore_msg', self.command_name, self.channel.name, dt)

        elif self.ignore_type == IgnoreType.PASSIVE_USAGE:
            m = Lang.lang(self.ignoring_instance, 'user_cmd_ignore_msg',
                          self.user.display_name, self.command_name, dt)

        elif self.ignore_type == IgnoreType.ACTIVE_USAGE:
            m = Lang.lang(self.ignoring_instance, 'user_cmd_ignore_msg',
                          self.user.display_name, self.command_name, dt)

        else:
            return str(self)

        return m


class Ignoring(BaseSubsystem):
    """Provides the ignoring subsystem"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.plugins.append(self)
        self.log = logging.getLogger(__name__)

        self.additional_cmds = []

        self.users = []
        self.cmds = []
        self.passive = []
        self.active = []

        # pylint: disable=unused-variable
        @self.bot.listen()
        async def on_ready():
            self._load()

    def get_ignore_list(self, ignore_type: IgnoreType):
        """Gets the list for the given IgnoreType or None if for the type is no list available."""
        if ignore_type == IgnoreType.USER:
            return self.users
        if ignore_type == IgnoreType.COMMAND:
            return self.cmds
        if ignore_type == IgnoreType.PASSIVE_USAGE:
            return self.passive
        if ignore_type == IgnoreType.ACTIVE_USAGE:
            return self.active
        return None

    def get_full_ignore_list(self):
        """Returns the full ignore list with all entries"""
        li = []
        li.extend(self.users)
        li.extend(self.cmds)
        li.extend(self.active)
        li.extend(self.passive)
        return li

    def get_full_ignore_len(self):
        return len(self.users) + len(self.cmds) + len(self.passive) + len(self.active)

    def _load(self):
        """
        Loads the ignore list from json
        """
        Storage.load(self)
        for el in Storage.get(self):
            self.add(IgnoreDataset.deserialize(self.bot, el, self), True)

    def save(self):
        """Saves the current ignorelist to json"""
        full_list = self.get_full_ignore_list()

        jsondata = []
        for el in full_list:
            jsondata.append(el.serialize())
        Storage.set(self, jsondata)
        Storage.save(self)

    #######
    # Additional commands
    #######

    def add_additional_command(self, command_name: str):
        """
        Adds a (custom) command to be ignorable

        :param command_name: The command name
        """
        self.additional_cmds.append(command_name)

    def get_additional_commands(self):
        """Return additional ignorable commands"""
        return self.additional_cmds

    #######
    # Adding
    #######

    def add(self, dataset: IgnoreDataset, disable_save_file: bool = False) -> IgnoreEditResult:
        """
        Adds a IgnoreDataset to ignore list and schedules necessary timers for auto-remove

        :param dataset: the dataset
        :param disable_save_file: disables saving ignore list in json file, useful for system startup
        :return: Code based on IgnoreEditResult
        """
        if dataset in self.get_ignore_list(dataset.ignore_type):
            return IgnoreEditResult.ALREADY_IN_LIST
        if dataset.until < datetime.now():
            return IgnoreEditResult.UNTIL_IN_PAST

        if dataset.until < datetime.max:
            timedict = timers.timedict(year=dataset.until.year, month=dataset.until.month,
                                       monthday=dataset.until.day, hour=dataset.until.hour,
                                       minute=dataset.until.minute)
            job = self.bot.timers.schedule(self._auto_remove_callback, timedict, repeat=False)
            job.data = dataset
            dataset.job = job

        ignore_list = self.get_ignore_list(dataset.ignore_type)
        ignore_list.append(dataset)
        if not disable_save_file:
            self.save()
        self.log.info("Added to ignore list: %s", dataset)
        return IgnoreEditResult.SUCCESS

    def add_user(self, user: discord.User, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds the user to the ignore list to block all interactions between the user with the bot.

        :param user: The user to block
        :param until: The datetime to auto-remove the user from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.USER, user=user, until=until, ignoring_instance=self)
        return self.add(dataset)

    def add_user_id(self, user_id: int, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds the user to the ignore list to block all interactions between the user with the bot.

        :param user_id: The id of the user to block
        :param until: The datetime to auto-remove the user from ignore list
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.add_user(user, until)

    def add_command(self, command_name: str, channel: discord.TextChannel,
                    until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds the command in the ignore list to disable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel: The channel in which the command will be disabled
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.COMMAND, command_name=command_name,
                                channel=channel, until=until, ignoring_instance=self)
        return self.add(dataset)

    def add_command_id(self, command_name: str, channel_id: int, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds the command in the ignore list to disable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel_id: The id of the channel in which the command will be disabled
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        channel = self.bot.get_channel(channel_id)
        return self.add_command(command_name, channel, until)

    def add_passive(self, user: discord.User, command_name: str, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds a active and passive usage block for the user for the command to ignore list
        to block any interactions of the user with the specific command.

        :param user: The user to block
        :param command_name: The command to block for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.PASSIVE_USAGE, user=user,
                                command_name=command_name, until=until, ignoring_instance=self)
        return self.add(dataset)

    def add_passive_uid(self, user_id: int, command_name: str, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds a active and passive usage block for the user for the command to ignore list
        to block any interactions of the user with the specific command.

        :param user_id: The id of the user to block
        :param command_name: The command to block for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.add_passive(user, command_name, until)

    def add_active(self, user: discord.User, command_name: str, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds a active usage block for the user for the command to ignore list
        to block the usage of the command for the specific user.

        :param user: The user to block
        :param command_name: The command to block for the user, must be the full qualified command name (eg. 'dsc set')
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.ACTIVE_USAGE, user=user,
                                command_name=command_name, until=until, ignoring_instance=self)
        return self.add(dataset)

    def add_active_uid(self, user_id: int, command_name: str, until: datetime = datetime.max) -> IgnoreEditResult:
        """
        Adds a active usage block for the user for the command to ignore list
        to block the usage of the command for the specific user.

        :param user_id: The user to block
        :param command_name: The command to block for the user, must be the full qualified command name (eg. 'dsc set')
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.add_active(user, command_name, until)

    #######
    # Removing
    #######

    def remove(self, dataset: IgnoreDataset) -> IgnoreEditResult:
        """
        Removes a IgnoreDataset from ignore list and removes it's scheduled timer

        :param dataset: the dataset
        :return: Code based on IgnoreEditResult
        """
        if dataset not in self.get_ignore_list(dataset.ignore_type):
            return IgnoreEditResult.NOT_IN_LIST

        dataset_index = self.get_ignore_list(dataset.ignore_type).index(dataset)
        listed_dataset = self.get_ignore_list(dataset.ignore_type)[dataset_index]
        if listed_dataset.job is not None:
            listed_dataset.job.cancel()

        self.get_ignore_list(dataset.ignore_type).remove(listed_dataset)
        self.save()
        self.log.info("Removed from ignore list: %s", listed_dataset)
        return IgnoreEditResult.SUCCESS

    async def _auto_remove_callback(self, job):
        """
        The auto-remove callback method

        :param job: the auto-remove job with the dataset
        """
        remove_result = self.remove(job.data)
        msg = "Attempt auto-removing {}, Result: {}".format(job.data, str(remove_result))
        await utils.write_mod_channel(msg)

    def remove_user(self, user: discord.User) -> IgnoreEditResult:
        """
        Removes the user from the ignore list and re-enables all interactions between the user with the bot.

        :param user: The user to re-enable
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.USER, user=user)
        return self.remove(dataset)

    def remove_user_id(self, user_id: int) -> IgnoreEditResult:
        """
        Removes the user from the ignore list and re-enables all interactions between the user with the bot.

        :param user_id: The id of the user to re-enable
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.remove_user(user)

    def remove_command(self, command_name: str, channel: discord.TextChannel) -> IgnoreEditResult:
        """
        Removes the command from the ignore list to re-enable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel: The channel in which the command will be re-enabled
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.COMMAND, command_name=command_name, channel=channel)
        return self.remove(dataset)

    def remove_command_id(self, command_name: str, channel_id: int) -> IgnoreEditResult:
        """
        Removes the command from the ignore list to re-enable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel_id: The id of the channel in which the command will be re-enabled
        :return: Code based on IgnoreEditResult
        """
        channel = self.bot.get_channel(channel_id)
        return self.remove_command(command_name, channel)

    def remove_passive(self, user: discord.User, command_name: str) -> IgnoreEditResult:
        """
        Removes the active and passive usage block for the user for the command from ignore list to re-enable any
        interactions of the user with the specific command.

        :param user: The user to re-enable
        :param command_name: The command to re-enable for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.PASSIVE_USAGE, user=user, command_name=command_name)
        return self.remove(dataset)

    def remove_passive_uid(self, user_id: int, command_name: str) -> IgnoreEditResult:
        """
        Removes the active and passive usage block for the user for the command from ignore list to re-enable any
        interactions of the user with the specific command.

        :param user_id: The id of the user to re-enable
        :param command_name: The command to re-enable for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.remove_passive(user, command_name)

    def remove_active(self, user: discord.User, command_name: str) -> IgnoreEditResult:
        """
        Removes the active usage block for the user for the command from ignore list to re-enable any
        interactions of the user with the specific command.

        :param user: The user to re-enable
        :param command_name: The command to block for the user, must be the full qualified command name (eg. 'dsc set')
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.ACTIVE_USAGE, user=user, command_name=command_name)
        return self.remove(dataset)

    def remove_active_uid(self, user_id: int, command_name: str) -> IgnoreEditResult:
        """
        Removes the active usage block for the user for the command from ignore list to re-enable any
        interactions of the user with the specific command.

        :param user_id: The id of the user to re-enable
        :param command_name: The command to block for the user, must be the full qualified command name (eg. 'dsc set')
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.remove_passive(user, command_name)

    #######
    # Checking
    #######

    @staticmethod
    def _user_name_check_func(user: discord.User):
        """The user name check function"""
        return get_best_username(user)

    @staticmethod
    def _user_id_check_func(user: discord.User):
        """The user id check function"""
        return user.id

    def _check_user(self, user_to_check, user_check_func) -> bool:
        """
        Performs the check if all bot interaction with user should be blocked.

        :param user_to_check: The user to check
        :param user_check_func: The function with the user check will be performed, must be func(discord.User)
        :return: True if user interactions should be blocked, otherwise False
        """
        ignore_list_user = self.get_ignore_list(IgnoreType.USER)
        for el in ignore_list_user:
            if user_check_func(el.user) == user_to_check:
                return True
        return False

    def check_user_id(self, user_id: int) -> bool:
        """
        Checks if all bot interaction with user should be blocked

        :param user_id: the user id
        :return: True if user interactions should be blocked, otherwise False
        """
        return self._check_user(user_id, self._user_id_check_func)

    def check_user_name(self, user_name: str) -> bool:
        """
        Checks if all bot interaction with user should be blocked

        :param user_name: the user name, returned by utils.get_best_username()
        :return: True if user interactions should be blocked, otherwise False
        """
        return self._check_user(user_name, self._user_name_check_func)

    def check_user(self, user: discord.User) -> bool:
        """
        Checks if all bot interaction with user should be blocked

        :param user: the user
        :return: True if user interactions should be blocked, otherwise False
        """
        return self.check_user_id(user.id)

    def check_command_name(self, command_name: str, channel: discord.TextChannel) -> bool:
        """
        Checks if the command is on the ignore list for the channel

        :param command_name: The full qualified command name
        :param channel: The channel
        :return: True if command is blocked in channel otherwise False
        """
        ignore_list = self.get_ignore_list(IgnoreType.COMMAND)
        for el in ignore_list:
            if el.command_name == command_name and el.channel == channel:
                return True
        return False

    def check_command(self, ctx: commands.Context) -> bool:
        """
        Checks if the context is invoked by a command which is on the ignore list
        for the channel in which the command was called.

        :param ctx: the command context
        :return: True if command is blocked in channel, otherwise False
        """
        cmd_name = ctx.command.qualified_name
        return self.check_command_name(cmd_name, ctx.channel)

    def _check_passive_usage(self, user_to_check, user_check_func, command_name: str) -> bool:
        """
        Performs the check if a command is active and passive blocked for the specific user.

        :param user_to_check: The user to check
        :param user_check_func: The function with the user check will be performed, must be func(discord.User)
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """
        if self._check_user(user_to_check, user_check_func):
            return True
        ignore_list_user_cmd = self.get_ignore_list(IgnoreType.PASSIVE_USAGE)
        for el in ignore_list_user_cmd:
            if user_check_func(el.user) == user_to_check and el.command_name == command_name:
                return True
        return False

    def check_passive_usage_uid(self, user_id: int, command_name: str) -> bool:
        """
        Checks if a command is active and passive blocked for the specific user id.

        :param user_id: The user id
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """

        return self._check_passive_usage(user_id, self._user_id_check_func, command_name)

    def check_passive_usage_uname(self, user_name: str, command_name: str) -> bool:
        """
        Checks if a command is active and passive blocked for the specific user name.

        :param user_name: The user name, returned by utils.get_best_username()
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """

        return self._check_passive_usage(user_name, self._user_name_check_func, command_name)

    def check_passive_usage(self, user: discord.User, command_name: str) -> bool:
        """
        Checks if a command is active and passive blocked for the specific user.

        :param user: The user
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """
        return self.check_passive_usage_uid(user.id, command_name)

    def _check_active_usage(self, user_to_check, user_check_func, command_name: str) -> bool:
        """
        Performs the check if a active command usage is blocked for the specific user.

        :param user_to_check: The user to check
        :param user_check_func: The function with the user check will be performed, must be func(discord.User)
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """
        if self._check_user(user_to_check, user_check_func):
            return True
        ignore_list_user_cmd = self.get_ignore_list(IgnoreType.ACTIVE_USAGE)
        for el in ignore_list_user_cmd:
            if user_check_func(el.user) == user_to_check and el.command_name == command_name:
                return True
        return False

    def check_active_usage_uid(self, user_id: int, command_name: str) -> bool:
        """
        Checks if a active command usage is blocked for the specific user id.

        :param user_id: The user id
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """

        return self._check_active_usage(user_id, self._user_id_check_func, command_name)

    def check_active_usage_uname(self, user_name: str, command_name: str) -> bool:
        """
        Checks if a active command usage is blocked for the specific user name.

        :param user_name: The user name, returned by utils.get_best_username()
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """

        return self._check_active_usage(user_name, self._user_name_check_func, command_name)

    def check_active_usage(self, user: discord.User, command_name: str) -> bool:
        """
        Checks if a active command usage is blocked for the specific user.

        :param user: The user
        :param command_name: The command name
        :return: True if user is blocked for command, otherwise False
        """
        return self.check_active_usage_uid(user.id, command_name)
