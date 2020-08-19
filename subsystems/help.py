from base import BaseSubsystem

from conf import Lang


class GeckiHelp(BaseSubsystem):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot

    def command_not_found(self, string):
        """
        This gets injected to discord.ext.commands.help.DefaultHelpCommand.
        :param string: help string
        :return: category help or error message
        """
        return Lang.lang(self, "cmd_not_found")
