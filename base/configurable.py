from typing import List, Any
from enum import Enum

from discord.ext.commands import Cog, Command


# pylint: disable=import-outside-toplevel
# pylint: disable=no-self-use
# pylint: disable=unused-argument


class NotLoadable(Exception):
    """
    Raised by plugins to signal that it was unable to load correctly.
    """


class PluginClassNotFound(Exception):
    """
    Raised when there is no Plugin class.
    """

    def __init__(self, members):
        super().__init__("Plugin class not found.")
        self.members = members


class NotFound(Exception):
    """
    Raised by override methods to signal that the method was not overridden.
    """


class ConfigurableType(Enum):
    """The Type of a Configurable"""
    SUBSYSTEM = 0
    COREPLUGIN = 1
    PLUGIN = 2


class Configurable:
    """Defines a class which the config of its instances can be managed by Config class"""

    def __init__(self):
        self.iodirs = {}
        self.can_configdump = True
        """Enables or disables that !configdump can dump the config of the plugin"""
        self.dump_except_keys = []  # type: List[str]
        """
        List of first level keys which won't be showed using !configdump and !storagedump.
        Effects main config/ storage and every container.
        """

    def default_config(self, container=None) -> Any:
        """
        Returns an empty default config
        """
        return {}

    def default_storage(self, container=None) -> Any:
        """
        Returns an empty default storage

        :param container: storage container name
        """
        return {}

    def get_lang_code(self) -> str:
        """
        Override this to return the plugin's lang code. Raise NotFound, return None or return bot.LANGUAGE_CODE
        to use the same language as the rest of the bot.

        :raises NotFound: Raise this to indicate no override.
        """
        raise NotFound()

    def get_lang(self):
        """
        Gets the lang dictionary for Config API.

        :raises NotFound: Raise this to indicate no override.
        """
        raise NotFound()

    def get_name(self):
        """
        Returns a human-readable plugin name.
        """
        return self.__module__.rsplit(".", 1)[1]

    def get_configurable_type(self):
        """
        Returns the ConfigurableType of self
        """
        raise NotImplementedError


class BaseSubsystem(Configurable):
    """The base class for all services"""

    def get_configurable_type(self):
        """
        Returns the ConfigurableType of self
        """
        return ConfigurableType.SUBSYSTEM


class BasePlugin(Cog, Configurable):
    """The base class for all plugins"""

    def __init__(self):
        Cog.__init__(self)
        Configurable.__init__(self)

    def get_configurable_type(self):
        """
        Returns the ConfigurableType of self
        """
        return ConfigurableType.PLUGIN

    async def shutdown(self):
        """
        Is called when the bot is shutting down. If you have cleanup to do, do it here.
        Needs to be a coroutine (async).
        """

    async def command_help(self, ctx, command):
        """
        Used to override the behavior of !help <command>. Raise NotFound to give control back to the help command.

        :param ctx: Context
        :param command: Command or Group instance
        :raises NotFound: Raise this to indicate that the behavior is not overridden.
        """
        raise NotFound()

    def command_help_string(self, command):
        """
        Override to return a help string that is determined at runtime. Overwrites command.help.

        :param command: Command that the help string is requested for.
        :return: Help string
        :raises NotFound: Raise this to indicate no override.
        """
        raise NotFound()

    def command_description(self, command):
        """
        Override to return a description that is determined at runtime. Supersedes command.description.

        :param command: Command that a description is requested for.
        :return: Description string
        :raises NotFound: Raise this to indicate no override.
        """
        raise NotFound()

    def command_usage(self, command):
        """
        Override to return a usage string that is determined at runtime. Supersedes command.usage.

        :param command: Command that a usage string is requested for.
        :return: Usage string
        :raises NotFound: Raise this to indicate no override.
        """
        raise NotFound()

    def sort_commands(self, ctx, command: Command, subcommands: List[Command]) -> List[Command]:
        """
        Override to sort the subcommands of `command` yourself.

        :param ctx: Context
        :param command: Command whose subcommands are to be sorted
        :param subcommands: List of commands to be sorted
        :return: Sorted list of commands
        """
        return sorted(subcommands, key=lambda x: x.name.lower())
