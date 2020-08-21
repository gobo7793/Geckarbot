from enum import Enum
from discord.ext.commands import Cog


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
