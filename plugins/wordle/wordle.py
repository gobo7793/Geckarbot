import logging

from nextcord.ext import commands

from base.configurable import BasePlugin
from base.data import Config, Lang
from botutils.setter import ConfigSetter
from botutils.utils import helpstring_helper, add_reaction
from services.helpsys import DefaultCategories


BASE_CONFIG = {
    "value": [int, 1],
}


class Plugin(BasePlugin, name="Testing and debug things"):

    def __init__(self):
        super().__init__()
        Config().bot.register(self, category=DefaultCategories.GAMES)
        self.logger = logging.getLogger(__name__)

        self.config_setter = ConfigSetter(self, BASE_CONFIG)

    def get_config(self, key):
        return Config.get(self).get(key, BASE_CONFIG[key][1])

    def default_storage(self, container=None):
        return {}

    def default_config(self, container=None):
        return {}

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    @commands.group(name="wordle")
    async def cmd_wordle(self, ctx):
        await Config().bot.helpsys.cmd_help(ctx, self, ctx.command)

    @commands.has_role(Config().BOT_ADMIN_ROLE_ID)
    @cmd_wordle.command(name="set", aliases=["config"], hidden=True)
    async def cmd_set(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        await self.config_setter.set_cmd(ctx, key, value)
