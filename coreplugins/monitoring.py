import pprint
from datetime import datetime

from base import BasePlugin, ConfigurableType

from discord.ext import commands

from botutils import converters
from botutils.stringutils import paginate
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
        for msg in paginate(self.bot.reaction_listener.callbacks,
                            prefix="**Reactions registrations:**\n",
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)

        timer_status = "up" if self.bot.timers.is_alive() else "down"
        for msg in paginate(self.bot.timers.jobs,
                            prefix="**Timers: Thread is {}; registrations:**\n".format(timer_status),
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)
        for msg in paginate(self.bot.dm_listener.registrations,
                            prefix="**DM Listeners:**\n",
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)

        presence_timer_status = "up" if self.bot.presence.is_timer_up else "down"
        for msg in paginate(list(self.bot.presence.messages.values()),
                            prefix="**Full presence entries, Timer is {}:**\n".format(presence_timer_status),
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)
        for msg in paginate(list(self.bot.ignoring.get_full_ignore_list()),
                            prefix="**Ignoring entries:**\n",
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)

    @commands.command(name="storagedump", help="Dumps plugin storage", usage="<plugin name>")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def storagedump(self, ctx, name):
        plugin = converters.get_plugin_by_name(self.bot, name)
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
        for el in paginate(dump, prefix=prefix, msg_prefix="```", msg_suffix="```"):
            await ctx.send(el)

    @commands.command(name="configdump", help="Dumps plugin config", usage="<plugin name>")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    # NOTE: Is called by "!dsc set config" and "!fantasy set config"
    async def configdump(self, ctx, name):
        plugin = converters.get_plugin_by_name(self.bot, name)
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
        for el in paginate(dump, prefix=prefix, msg_prefix="```", msg_suffix="```"):
            await ctx.send(el)

    @commands.command(name="date", help="Current date and time")
    async def date(self, ctx):
        now = datetime.now()
        await ctx.send(now.strftime('%d.%m.%Y %H:%M:%S.%f'))

    @commands.command(name="debug", help="Print or change debug mode at runtime", usage="[true|on|off|false|toggle]")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def debug(self, ctx, arg=None):
        toggle = None
        if arg is not None:
            arg = arg.lower()
        if arg == "toggle":
            toggle = not self.bot.DEBUG_MODE
        elif arg == "on" or arg == "true" or arg == "set":
            toggle = True
        elif arg == "off" or arg == "false":
            toggle = False

        if toggle is None:
            if self.bot.DEBUG_MODE:
                await ctx.send("I am in debug mode.")
            else:
                await ctx.send("I am not in debug mode.")
        else:
            self.bot.set_debug_mode(toggle)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
