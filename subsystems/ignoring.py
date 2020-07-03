import enum

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
    """Blocks all interactions between user and bot. Disables command_name and channel arguments in IgnoreDataset."""
    Command = 2
    """Disables command usage in specific channel. Disables user argument in IgnoreDataset."""
    User_Command = 3
    """Blocks any interactions for an user on a specific command. Disables channel argument in IgnoreDataset."""


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
            str(self.ignore_type), utils.get_best_username(self.user), self.command_name,
            self.channel.name, self.until)

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
        """
        Returns all ignore list entries of the given IgnoreType.
        """
        return [el for el in self.ignorelist if el.ignore_type == ignore_type]

    def load(self):
        """Loads the ignorelist json"""
        jsondata = Config()._read_config_file(ignoring_file_name)
        for el in jsondata:
            self.add(IgnoreDataset.deserialize(self.bot, el))

    def save(self):
        """Saves the current ignorelist to json"""
        jsondata = []
        for el in self.ignorelist:
            jsondata.append(el.serialize())
        Config()._write_config_file(ignoring_file_name, jsondata)

    def add(self, dataset: IgnoreDataset):
        """
        Adds a IgnoreDataset to ignore list and schedules necessary timers for auto-remove
        :param dataset: the dataset
        :return: True if added, False if dataset already in list
        """
        if dataset in self.ignorelist:
            return False

        self.ignorelist.append(dataset)
        if dataset.until < datetime.max:
            timedict = timers.timedict(year=dataset.until.year, month=dataset.until.month,
                                       monthday=dataset.until.day, hour=dataset.until.hour,
                                       minute=dataset.until.minute)
            job = self.bot.timers.schedule(self.auto_remove_callback, timedict, repeat=False)
            job.data = dataset
            dataset.job = job
        self.save()
        return True

    async def auto_remove_callback(self, job):
        """
        The auto-remove callback method
        :param job: the auto-remove job with the dataset
        """
        remove_result = self.remove(job.data)
        msg = "Attempt auto-removing {}, Result: {}".format(job.data.to_raw_message(), remove_result)
        await utils.write_admin_channel(self.bot, msg)

    def remove(self, dataset: IgnoreDataset):
        """
        Removes a IgnoreDataset from ignore list and removes it's scheduled timer
        :param dataset: the dataset
        :return: True if dataset is removed, False if dataset not in list
        """
        if dataset not in self.ignorelist:
            return False

        self.ignorelist.remove(dataset)
        if dataset.job is not None:
            dataset.job.cancel()

        self.save()
        return True

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
