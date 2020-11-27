import pprint
from datetime import datetime
from typing import Union

import discord
from discord.ext import commands

from base import BasePlugin, ConfigurableType
from botutils import converters
from botutils.permchecks import is_botadmin
from botutils.stringutils import paginate
from botutils.converters import get_best_username as gbu
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
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
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
        for msg in paginate(self.bot.dm_listener.registrations.keys(),
                            prefix="**DM Listeners:**\n",
                            suffix="\n",
                            f=lambda x: self.bot.dm_listener.registrations[x],
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

        liveticker_list = []
        for leag in self.bot.liveticker.registrations.values():
            liveticker_list.append(leag)
            liveticker_list.extend("- {}".format(str(lt_reg)) for lt_reg in leag.registrations)
        for msg in paginate(liveticker_list,
                            prefix="**Liveticker Registrations:**\n",
                            suffix="\n",
                            if_empty="None"):
            await ctx.send(msg)

    @commands.command(name="storagedump", help="Dumps plugin storage", usage="<plugin name>")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def storagedump(self, ctx, name):
        plugin = converters.get_plugin_by_name(name)
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
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    # NOTE: Is called by "!dsc set config" and "!fantasy set config"
    async def configdump(self, ctx, name):
        plugin = converters.get_plugin_by_name(name)
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
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
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

    @commands.command(name="dmreg")
    async def cmd_listdmreg(self, ctx, user: Union[discord.Member, discord.User, None] = None):
        print(user)
        if user is None:
            user = ctx.author

        msgs = []
        for key in self.bot.dm_listener.registrations:
            reg = self.bot.dm_listener.registrations[key]
            if reg.user == user:
                if reg.blocking:
                    block = Lang.lang(self, "dm_true")
                else:
                    block = Lang.lang(self, "dm_false")
                msgs.append(Lang.lang(self, "dm_base_format", key, reg.name, block))

        if not msgs:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await ctx.send(Lang.lang(self, "dm_empty_result", gbu(user)))
            return

        prefix = Lang.lang(self, "dm_result_prefix", gbu(user))
        for msg in paginate(msgs, prefix=prefix):
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await ctx.send(msg)

    @commands.command(name="freedm")
    async def cmd_dmkill(self, ctx, reg_id: int):
        try:
            reg = self.bot.dm_listener.registrations[reg_id]
        except KeyError:
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        if reg.user != ctx.author and not is_botadmin(reg.user):
            await ctx.message.add_reaction(Lang.CMDNOPERMISSIONS)
            return

        await reg.kill()
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
