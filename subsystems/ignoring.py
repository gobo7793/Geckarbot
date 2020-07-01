import discord
from datetime import datetime

from conf import Config
from botutils import utils


ignoring_file_name = "ignoring"

class IgnoreDataset:
    """The ignoring dataset"""

    def __init__(self, user: discord.User = None, command_name: str = "",
                 channel: discord.TextChannel = None, until: datetime = datetime.max):
        """
        Creates a new ignoring dataset.
        Not needed args can be None, eg for ignoring user completely the args command_name and channel.
        :param user: The user to ignore
        :param command_name: The command name to disabling for a user or completely in a channel
        :param channel: The channel in which a command is disabled
        :param until: The datetime on which the ignoring entry will be auto-removed
        """
        self.user = user
        self.command_name = command_name
        self.channel = channel
        self.until = until

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
        return IgnoreDataset(user, d["command_name"], channel, d["until"])

    def to_raw_message(self):
        """
        Builds an raw output message with the raw data
        :return: The raw message
        """
        return "IgnoreDataset: User: {}, Command: {}, Channel: {}, Until: {}".format(
            utils.get_best_username(self.user), self.command_name, self.channel.name, self.until)

    def to_message(self):
        """
        Builds an well formatted output message for listing the entries on ignore list.
        Formats:
        - Username is on ignore list [for command command_name] until.../forever.
        - Command command_name is disabled in channel Channelname until.../forever.
        :return: The well formatted message
        """
        m = ""

        if self.user is not None:
            m += "{} is on ignore list ".format(utils.get_best_username(self.user))
            if self.command_name:
                m += " for command "
        else:
            m += "Command "

        if self.command_name:
            m += self.command_name
            if self.user is None:
                m += " is disabled"
            elif self.channel is not None:
                m += " in channel {}".format(self.channel.name)

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

    def load(self):
        """Loads the ignorelist json"""
        jsondata = Config()._read_config_file(ignoring_file_name)
        for el in jsondata:
            self.ignorelist.append(IgnoreDataset.deserialize(self.bot, el))

    def save(self):
        """Saves the current ignorelist to json"""
        jsondata = []
        for el in self.ignorelist:
            jsondata.append(el.serialize())
        Config()._write_config_file(ignoring_file_name, jsondata)
