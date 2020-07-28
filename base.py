from discord.ext.commands import Cog


class Configurable:
    """Defines a class which the config of its instances can be managed by Config class"""

    def __init__(self):
        super().__init__()
        self.can_reload = False

    def default_config(self):
        """
        Returns an empty default config
        """
        return {}

    def get_lang(self):
        """
        Gets the lang dictionary for Config API.
        """
        return None


class BaseSubsystem(Configurable):
    """The base class for all subsystems"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot


class BasePlugin(Cog, Configurable):
    """The base class for all plugins"""
    def __init__(self, bot):
        Cog.__init__(self)
        Configurable.__init__(self)
        self.bot = bot

    async def shutdown(self):
        """
        Is called when the bot is shutting down. If you have cleanup to do, do it here.
        Needs to be a coroutine (async).
        """
        pass