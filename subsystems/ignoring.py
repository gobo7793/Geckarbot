import enum
import logging

import discord
from discord.ext import commands
from datetime import datetime

from conf import Config
from botutils import utils
from subsystems import timers

ignoring_file_name = "ignoring"


class IgnoreType(enum.IntEnum):
    """The possible types for ignore list entries."""

    NA = 0
    """Not defined"""
    User = 1
    """Blocks any interactions between user and bot. Disables command_name and channel arguments in IgnoreDataset."""
    Command = 2
    """Disables command usage in specific channel. Disables user argument in IgnoreDataset."""
    User_Command = 3
    """Blocks any interactions for an user on a specific command. Disables channel argument in IgnoreDataset."""


class IgnoreEditResult(enum.Enum):
    """Return codes for adding and removing datasets to ignore list."""

    Success = 0
    """Successfully added/removed to ignore list"""
    Already_in_list = 1
    """Dataset is already in list."""
    Not_in_list = 2
    """Dataset is not in list."""
    Until_in_past = 3
    """Until datetime for auto-remove is in past, dataset was not added to ignore list."""


class IgnoreDataset:
    """
    The ignoring dataset.
    Supports equal operation and checks equality based on type, user id, command name and channel id.
    """

    def __init__(self, ignore_type: IgnoreType, user: discord.User = None, command_name: str = "",
                 channel: discord.TextChannel = None, until: datetime = datetime.max, job: timers.Job = None):
        """
        Creates a new ignoring dataset.
        Not needed args can be None, eg for ignoring user completely the args command_name and channel.
        Disabled arguments based on type raises ValueError.

        :param ignore_type: The type of the ignore dataset, defines not possible arguments
        :param user: The user to ignore. For IgnoreType.User and IgnoreType.User_Command.
        :param command_name: The command name to disabling for a user or completely in a channel.
            For IgnoreType.Command and IgnoreType.User_Command.
        :param channel: The channel in which a command is disabled. For IgnoreType.Command.
        :param until: The datetime on which the ignoring entry will be auto-removed. Possible for all types.
        :param job: The timer subsystem job for auto-remove
        """
        if (type == IgnoreType.User
                and (user is None
                     or command_name
                     or channel is not None)):
            raise ValueError("User blocking only accepts the user argument.")
        if (type == IgnoreType.Command
                and (user is not None
                     or not command_name
                     or channel is None)):
            raise ValueError("Command disabling only needs both of command_name and channel arguments.")
        if (type == IgnoreType.User_Command
                and (user is None
                     or not command_name
                     or channel is not None)):
            raise ValueError("Blocking user interactions only needs both of user and command_name arguments.")

        self.ignore_type = ignore_type
        self.user = user
        self.command_name = command_name
        self.channel = channel
        self.until = until
        self.job = job

    def __eq__(self, other):
        if isinstance(other, IgnoreDataset):
            type_res = self.ignore_type == other.ignore_type
            user_res = IgnoreDataset._eq(self.user, other.user)
            cmd_res = self.command_name == other.command_name
            chan_res = IgnoreDataset._eq(self.channel, other.channel)

            return type_res and user_res and cmd_res and chan_res
        return False

    @classmethod
    def _eq(cls, self, other):
        """__eq__ helper method"""
        if self is not None and other is not None:
            return self == other
        else:
            return self is None and other is None

    def serialize(self):
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
    def deserialize(cls, bot, d):
        """
        Constructs a IgnoreDataset object from a dict.

        :param bot: Geckarbot reference
        :param d: dict made by serialize()
        :return: IgnoreDataset object
        """
        user = bot.guild.get_member(d["userid"])
        if user is None:
            user = bot.get_user(d["userid"])
        channel = bot.get_channel(d["userid"])
        return IgnoreDataset(d["type"], user, d["command_name"], channel, d["until"])

    def to_raw_message(self):
        """
        Builds an raw output message with the raw data.

        Format: IgnoreDataset: User: user_name, Command: command_name, Channel: channel_name, Until: datetime

        :return: The raw message
        """
        return "IgnoreDataset: Type: {}, User: {}, Command: {}, Channel: {}, Until: {}".format(
            str(self.ignore_type), self.user, self.command_name, self.channel, self.until)

    def to_message(self):
        """
        Builds an well formatted output message for listing the entries on ignore list.

        Format for User or User_Command IgnoreType:
            User user_name will be ignored [for command command_name] until.../forever.
        Format for Command IgnoreType:
            Command command_name is disabled in channel channel_name until.../forever.
        For other IgnoreTypes the raw message will be returned.

        :return: The well formatted message
        """

        if self.ignore_type == IgnoreType.User:
            m = "User {} will be ignored".format(utils.get_best_username(self.user))

        elif self.ignore_type == IgnoreType.Command:
            m = "User {} will be ignored for command {}".format(utils.get_best_username(self.user), self.command_name)

        elif self.ignore_type == IgnoreType.User_Command:
            m = "Command {} is disabled in channel {}".format(self.command_name, self.channel.name)

        else:
            return self.to_raw_message()

        if self.until < datetime.max:
            m += " until {}.".format(self.until.strftime("%d.%m.%Y, %H:%M"))
        else:
            m += " forever."

        return m


class Ignoring:
    """Provides the ignoring subsystem"""

    def __init__(self, bot):
        self.bot = bot
        self.ignorelist = []

        @bot.listen()
        async def on_ready():
            self.load()

    def filter_ignore_list(self, ignore_type: IgnoreType):
        """Returns all ignore list entries of the given IgnoreType."""
        return [el for el in self.ignorelist if el.ignore_type == ignore_type]

    def load(self):
        """Loads the ignorelist json"""
        jsondata = Config()._read_config_file(ignoring_file_name)
        if jsondata is not None:
            for el in jsondata:
                self.add(IgnoreDataset.deserialize(self.bot, el))

    def save(self):
        """Saves the current ignorelist to json"""
        jsondata = []
        for el in self.ignorelist:
            jsondata.append(el.serialize())
        Config()._write_config_file(ignoring_file_name, jsondata)

    #######
    # Adding
    #######

    def add(self, dataset: IgnoreDataset):
        """
        Adds a IgnoreDataset to ignore list and schedules necessary timers for auto-remove

        :param dataset: the dataset
        :return: Code based on IgnoreEditResult
        """
        if dataset in self.ignorelist:
            return IgnoreEditResult.Already_in_list
        if dataset.until < datetime.now():
            return IgnoreEditResult.Until_in_past

        if dataset.until < datetime.max:
            timedict = timers.timedict(year=dataset.until.year, month=dataset.until.month,
                                       monthday=dataset.until.day, hour=dataset.until.hour,
                                       minute=dataset.until.minute)
            job = self.bot.timers.schedule(self._auto_remove_callback, timedict, repeat=False)
            job.data = dataset
            dataset.job = job

        self.ignorelist.append(dataset)
        self.save()
        logging.info("Added to ignore list: {}".format(dataset.to_raw_message()))
        return IgnoreEditResult.Success

    def add_user(self, user: discord.User, until: datetime = datetime.max):
        """
        Adds the user to the ignore list to block all interactions between the user with the bot.

        :param user: The user to block
        :param until: The datetime to auto-remove the user from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.User, user=user, until=until)
        return self.add(dataset)

    def add_user_id(self, user_id: int, until: datetime = datetime.max):
        """
        Adds the user to the ignore list to block all interactions between the user with the bot.

        :param user_id: The id of the user to block
        :param until: The datetime to auto-remove the user from ignore list
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.add_user(user, until)

    def add_command(self, command_name: str, channel: discord.TextChannel, until: datetime = datetime.max):
        """
        Adds the command in the ignore list to disable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel: The channel in which the command will be disabled
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.Command, command_name=command_name, channel=channel, until=until)
        return self.add(dataset)

    def add_command_id(self, command_name: str, channel_id: int, until: datetime = datetime.max):
        """
        Adds the command in the ignore list to disable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel_id: The id of the channel in which the command will be disabled
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        channel = self.bot.get_channel(channel_id)
        return self.add_command(command_name, channel, until)

    def add_user_command(self, user: discord.User, command_name: str, until: datetime = datetime.max):
        """
        Adds the user and command to ignore list to block any interactions of the user with the specific command.

        :param user: The user to block
        :param command_name: The command to block for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.User_Command, user=user, command_name=command_name, until=until)
        return self.add(dataset)

    def add_user_id_command(self, user_id: int, command_name: str, until: datetime = datetime.max):
        """
        Adds the user and command to ignore list to block any interactions of the user with the specific command.

        :param user_id: The id of the user to block
        :param command_name: The command to block for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :param until: The datetime to auto-remove the command from ignore list
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.add_user_command(user, command_name, until)

    #######
    # Removing
    #######

    def remove(self, dataset: IgnoreDataset):
        """
        Removes a IgnoreDataset from ignore list and removes it's scheduled timer

        :param dataset: the dataset
        :return: Code based on IgnoreEditResult
        """
        if dataset not in self.ignorelist:
            return IgnoreEditResult.Not_in_list

        dataset_index = self.ignorelist.index(dataset)
        listed_dataset = self.ignorelist[dataset_index]
        if listed_dataset.job is not None:
            listed_dataset.job.cancel()

        self.ignorelist.remove(listed_dataset)
        self.save()
        logging.info("Removed from ignore list: {}".format(listed_dataset.to_raw_message()))
        return IgnoreEditResult.Success

    async def _auto_remove_callback(self, job):
        """
        The auto-remove callback method

        :param job: the auto-remove job with the dataset
        """
        remove_result = self.remove(job.data)
        msg = "Attempt auto-removing {}, Result: {}".format(job.data.to_raw_message(), str(remove_result))
        await utils.write_admin_channel(self.bot, msg)

    def remove_user(self, user: discord.User):
        """
        Removes the user from the ignore list and re-enables all interactions between the user with the bot.

        :param user: The user to re-enable
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.User, user=user)
        return self.remove(dataset)

    def remove_user_id(self, user_id: int):
        """
        Removes the user from the ignore list and re-enables all interactions between the user with the bot.

        :param user_id: The id of the user to re-enable
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.remove_user(user)

    def remove_command(self, command_name: str, channel: discord.TextChannel):
        """
        Removes the command from the ignore list to re-enable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel: The channel in which the command will be re-enabled
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.Command, command_name=command_name, channel=channel)
        return self.remove(dataset)

    def remove_command_id(self, command_name: str, channel_id: int):
        """
        Removes the command from the ignore list to re-enable the command in the specific channel.

        :param command_name: The full qualified command name (eg. 'dsc set')
        :param channel_id: The id of the channel in which the command will be re-enabled
        :return: Code based on IgnoreEditResult
        """
        channel = self.bot.get_channel(channel_id)
        return self.remove_command(command_name, channel)

    def remove_user_command(self, user: discord.User, command_name: str):
        """
        Removes the user and command from ignore list to re-enable any interactions
        of the user with the specific command.

        :param user: The user to re-enable
        :param command_name: The command to re-enable for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :return: Code based on IgnoreEditResult
        """
        dataset = IgnoreDataset(IgnoreType.User_Command, user=user, command_name=command_name)
        return self.remove(dataset)

    def remove_user_id_command(self, user_id: int, command_name: str):
        """
        Removes the user and command from ignore list to re-enable any interactions
        of the user with the specific command.

        :param user_id: The id of the user to re-enable
        :param command_name: The command to re-enable for the user, Should be, but not necessarily, the full qualified
            command name. Depending on the checking implementation for the specific command.
        :return: Code based on IgnoreEditResult
        """
        user = self.bot.get_user(user_id)
        return self.remove_user_command(user, command_name)

    #######
    # Checking
    #######

    def check_user_id(self, user_id: int):
        """
        Checks if all bot interaction with user should be blocked

        :param user_id: the user id
        :return: True if user interactions should be blocked, otherwise False
        """
        for el in self.filter_ignore_list(IgnoreType.User):
            if el.user.id == user_id:
                return True
        return False

    def check_user(self, user: discord.User):
        """
        Checks if all bot interaction with user should be blocked

        :param user: the user
        :return: True if user interactions should be blocked, otherwise False
        """
        return self.check_user_id(user.id)

    def check_command(self, ctx: commands.Context):
        """
        Checks if the context is invoked by a command which is on the ignore list
        for the channel in which the command was called.

        :param ctx: the command context
        :return: True if command is blocked in channel, otherwise False
        """
        cmd_name = ctx.command.qualified_name
        for el in self.filter_ignore_list(IgnoreType.Command):
            if el.command_name == cmd_name and el.channel == ctx.channel:
                return True
        return False

    def check_user_id_command(self, user_id: int, command_name: str):
        """
        Checks if the user is blocked for all interactions with the command.

        :param user_id: the user id
        :param command_name: the command name
        :return: True if user is blocked for command, otherwise False
        """
        for el in self.filter_ignore_list(IgnoreType.User_Command):
            if el.user.id == user_id and el.command_name == command_name:
                return True
        return False

    def check_user_command(self, user: discord.User, command_name: str):
        """
        Checks if the user is blocked for all interactions with the command.

        :param user: the user
        :param command_name: the command name
        :return: True if user is blocked for command, otherwise False
        """
        return self.check_user_id_command(user.id, command_name)
