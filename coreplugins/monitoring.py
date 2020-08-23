import pprint

from base import BasePlugin, ConfigurableType

from discord.ext import commands

from botutils import utils, converter
from conf import Storage, Config, Lang
from subsystems import help


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.ADMIN)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    @commands.command(name="subsys", help="Shows registrations on subsystems")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def subsys(self, ctx):
        for msg in utils.paginate(self.bot.reaction_listener.callbacks,
                                  prefix="**Reactions registrations:**\n",
                                  suffix="\n"):
            await ctx.send(msg)
        for msg in utils.paginate(self.bot.timers.jobs,
                                  prefix="**Timer registrations:**\n",
                                  suffix="\n"):
            await ctx.send(msg)
        for msg in utils.paginate(self.bot.dm_listener.callbacks,
                                  prefix="**DM Listeners:**\n",
                                  suffix="\n"):
            await ctx.send(msg)

        await ctx.invoke(self.bot.get_command("disable list"))

    @commands.command(name="storagedump", help="Dumps plugin storage", usage="<plugin name>")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def storagedump(self, ctx, name):
        plugin = converter.get_plugin_by_name(self.bot, name)
        if plugin is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Plugin {} not found.".format(name))
            return
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

        dump = pprint.pformat(Storage.get(plugin), indent=4).split("\n")
        prefix = ""
        if not Storage.has_structure(plugin):
            prefix = "**Warning: plugin {} does not have a storage structure.** " \
                     "This is the default storage.".format(name)
        for el in utils.paginate(dump, prefix=prefix, msg_prefix="```", msg_suffix="```"):
            await ctx.send(el)

    @commands.command(name="configdump", help="Dumps plugin config", usage="<plugin name>")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    # NOTE: Will be invoked via "!dsc set config"
    async def configdump(self, ctx, name):
        plugin = converter.get_plugin_by_name(self.bot, name)
        if plugin is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Plugin {} not found.".format(name))
            return
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

        dump = pprint.pformat(Config.get(plugin), indent=4).split("\n")
        prefix = ""
        if not Config.has_structure(plugin):
            prefix = "**Warning: plugin {} does not have a config structure.** " \
                     "This is the default config.".format(name)
        for el in utils.paginate(dump, prefix=prefix, msg_prefix="```", msg_suffix="```"):
            await ctx.send(el)
