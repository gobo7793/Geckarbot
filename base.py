from enum import Enum
from discord.ext.commands import Cog


class NotLoadable(Exception):
    """
    Raised by plugins to signal that it was unable to load correctly.
    """
    pass


class NotFound(Exception):
    """
    Raised by override methods to signal that the method was not overridden.
    """
    pass


class ConfigurableType(Enum):
    """The Type of a Configurable"""
    SUBSYSTEM = 0,
    COREPLUGIN = 1,
    PLUGIN = 2


class Configurable:
    """Defines a class which the config of its instances can be managed by Config class"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.can_reload = False

    def default_config(self):
        """
        Returns an empty default config
        """
        return {}

    def default_storage(self):
        """
        Returns an empty default storage
        """
        return {}

    def get_lang(self):
        """
        Gets the lang dictionary for Config API.
        """
        return None

    def get_name(self):
        """
        Returns a human-readable plugin name.
        """
        return self.__module__.rsplit(".", 1)[1]

    def get_configurable_type(self):
        """
        Returns the ConfigurableType of self
        """
        raise NotImplemented


class BaseSubsystem(Configurable):
    """The base class for all subsystems"""
    def __init__(self, bot):
        super().__init__(bot)

    def get_configurable_type(self):
        """
        Returns the ConfigurableType of self
        """
        return ConfigurableType.SUBSYSTEM


class BasePlugin(Cog, Configurable):
    """The base class for all plugins"""
    def __init__(self, bot):
        Cog.__init__(self)
        Configurable.__init__(self, bot)

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
        pass

    async def command_help(self, ctx, command):
        """
        Used to override command help. Raise NotFound to give control back to the help command.
        :param ctx: Context
        :param command: Command or Group instance
        """
        raise NotFound()

    def command_help_string(self, command):
        """
        Override to return a help string that is determined at runtime. Overwrites command.help.
        :param command: Command that the help string is requested for.
        :return: Help string
        """
        raise NotFound()

    def command_description(self, command):
        """
        Override to return a description that is determined at runtime. Supersedes command.description.
        :param command: Command that a description is requested for.
        :return: Description string
        """
        raise NotFound()

    def command_usage(self, command):
        """
        Override to return a usage string that is determined at runtime. Supersedes command.usage.
        :param command: Command that a usage string is requested for.
        :return: Usage string
        """
        raise NotFound()

    def sort_subcommands(self, command, subcommands):
        """
        Override to sort the subcommands of `command` yourself.
        :param command: Command whose subcommands are to be sorted
        :param subcommands: List of commands to be sorted
        :return: Sorted list of commands
        """
        return sorted(subcommands, key=lambda x: x.name.lower())
