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
from botutils.utils import add_reaction
from conf import Storage, Config, Lang
from subsystems import help


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.ADMIN)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    def default_config(self):
        return {
            'max_dump': 5  # maximum storage/configdump messages to show
        }

    @commands.command(name="subsys", help="Shows registrations on subsystems",
                      description="Shows registrations on subsystems. If a subsystem name is given, "
                                  "only registrations for this subsystem will be shown.",
                      usage="[dmlisteners|ignoring|liveticker|presence|reactions|timers]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def subsys(self, ctx, subsystem=""):
        if not subsystem or subsystem == "reactions":
            reaction_prefix = "**{} Reactions registrations:**\n".format(len(self.bot.reaction_listener.callbacks))
            for msg in paginate(self.bot.reaction_listener.callbacks,
                                prefix=reaction_prefix,
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

        if not subsystem or subsystem == "timers":
            timer_status = "up" if self.bot.timers.is_alive() else "down"
            timer_prefix = "**{} Timers: Thread is {}; registrations:**\n".format(len(self.bot.timers.jobs), timer_status)
            for msg in paginate(self.bot.timers.jobs,
                                prefix=timer_prefix,
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

        if not subsystem or subsystem == "dmlisteners":
            dmregs = self.bot.dm_listener.registrations
            if not dmregs:
                dmregs = {0: "None"}
            dm_prefix = "**{} DM Listeners:**\n".format(len(self.bot.dm_listener.registrations))
            for msg in paginate([x for x in dmregs.keys()],
                                prefix=dm_prefix,
                                suffix="\n",
                                f=lambda x: dmregs[x]):
                await ctx.send(msg)

        if not subsystem or subsystem == "presence":
            presence_timer_status = "up" if self.bot.presence.is_timer_up else "down"
            presence_prefix = "**{} Presence entries, Timer is {}:**\n".format(len(self.bot.presence.messages),
                                                                               presence_timer_status)
            for msg in paginate(list(self.bot.presence.messages.values()),
                                prefix=presence_prefix,
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

        if not subsystem or subsystem == "ignoring":
            ignoring_prefix = "**{} Ignoring entries:**\n".format(self.bot.ignoring.get_full_ignore_len())
            for msg in paginate(list(self.bot.ignoring.get_full_ignore_list()),
                                prefix=ignoring_prefix,
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

        if not subsystem or subsystem == "liveticker":
            for msg in self.liveticker_msgs():
                await ctx.send(msg)

    async def dump(self, ctx, iodir, iodir_str, name, container=None):
        plugin = converters.get_plugin_by_name(name)
        if plugin is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("Plugin {} not found.".format(name))
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        prefix = ""

        async with ctx.typing():
            # List existing structures when called on default container
            if container is None:
                containers = ", ".join(["`{}`".format(el) for el in iodir.data(plugin).structures() if el is not None])
                if containers:
                    prefix += "Available containers: {}\n".format(containers)

            dump = pprint.pformat(iodir.get(plugin, container=container), indent=4).split("\n")
            if not iodir.data(plugin).has_structure(container):
                prefix += "**Warning: plugin {} does not have the {} structure {}.** " \
                          "This is the default {}.".format(name, iodir_str, container, iodir_str)

        counter = 0
        for el in paginate(dump, prefix=prefix, msg_prefix="```", msg_suffix="```", prefix_within_msg_prefix=False):
            counter += 1
            if counter > Config.get(self)["max_dump"]:
                await ctx.send("There are more data in dump which won't be shown.")
                return
            await ctx.send(el)

    @commands.command(name="storagedump", help="Dumps plugin storage", usage="<plugin name> [container]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def storagedump(self, ctx, name, container=None):
        await self.dump(ctx, Storage, "storage", name, container=container)

    # Disabled for security reasons, we have API keys, passwords etc in these files
    # @commands.command(name="configdump", help="Dumps plugin config", usage="<plugin name> [container]")
    # @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def configdump(self, ctx, name, container=None):
        await self.dump(ctx, Config, "config", name, container=container)

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

    @commands.command(name="livetickerlist", help="Debug info for liveticker")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def liveticker_list(self, ctx):
        for msg in self.liveticker_msgs():
            await ctx.send(msg)

    def liveticker_msgs(self):
        liveticker_list = []
        for leag in self.bot.liveticker.registrations.values():
            liveticker_list.append("\u2b1c {}".format(str(leag)))
            liveticker_list.extend("\u25ab {}".format(str(lt_reg)) for lt_reg in leag.registrations)
        return paginate(liveticker_list, prefix="**Liveticker Registrations:**\n", suffix="\n", if_empty="None")

    @commands.command(name="livetickerkill", help="Kills all liveticker registrations")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def liveticker_kill(self, ctx):
        for reg in list(self.bot.liveticker.registrations.values()):
            reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

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
