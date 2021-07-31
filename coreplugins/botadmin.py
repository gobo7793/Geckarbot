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
from botutils.utils import add_reaction, write_debug_channel
from data import Storage, Config, Lang
from subsystems.helpsys import DefaultCategories


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self, DefaultCategories.ADMIN)

        # Write cmd deletions to debug chan
        @bot.event
        async def on_message_delete(msg):
            if msg.content.startswith("!"):
                event_name = "Command deletion"
            elif msg.content.startswith("+"):
                event_name = "Custom command deletion"
            else:
                return
            e = discord.Embed()
            e.add_field(name="Event", value=event_name)
            e.add_field(name="Author", value=gbu(msg.author))
            e.add_field(name="Command", value=msg.content)
            e.add_field(name="Channel", value=msg.channel)
            await write_debug_channel(e)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    def default_config(self):
        return {
            'max_dump': 4  # maximum storage/configdump messages to show
        }

    @commands.command(name="subsys", help="Shows registrations on subsystems",
                      description="Shows registrations on subsystems. If a subsystem name is given, "
                                  "only registrations for this subsystem will be shown.",
                      usage="[dmlisteners|ignoring|liveticker|presence|reactions|timers]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_subsys(self, ctx, subsystem=""):
        if not subsystem or subsystem == "reactions":
            reaction_prefix = "**{} Reactions registrations:**\n".format(len(self.bot.reaction_listener.callbacks))
            for msg in paginate(self.bot.reaction_listener.callbacks,
                                prefix=reaction_prefix,
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

        if not subsystem or subsystem == "timers":
            timer_prefix = "**{} Timers; registrations:**\n".format(len(self.bot.timers.jobs))
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
            for msg in paginate(list(dmregs),
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
            liveticker_list = []
            for src in self.bot.liveticker.registrations.values():
                for leag in src.values():
                    liveticker_list.append("\u2b1c {}".format(str(leag)))
                    liveticker_list.extend("\u25ab {}".format(str(lt_reg)) for lt_reg in leag.registrations)
            for msg in paginate(liveticker_list,
                                prefix="**Liveticker Registrations:**\n",
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

    async def _dump(self, ctx, iodir, iodir_str, name, container=None):
        plugin = converters.get_plugin_by_name(name)
        if plugin is None:
            if name == "ignoring":
                plugin = self.bot.ignoring
            elif name == "liveticker":
                plugin = self.bot.liveticker
            elif name == "presence":
                plugin = self.bot.presence
            else:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send("Plugin {} not found.".format(name))
                return
        if iodir is Config and not plugin.can_configdump:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("Config of plugin {} can't be dumped.".format(name))
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        prefix = ""

        async with ctx.typing():
            # List existing structures when called on default container
            if container is None:
                containers = ", ".join(["`{}`".format(el) for el in iodir.data(plugin).structures() if el is not None])
                if containers:
                    prefix += "Available containers: {}\n".format(containers)

            origin = iodir.get(plugin, container=container)
            if isinstance(origin, list):
                dump = origin
            else:
                dump = {}
                has_not_shown_keys = False
                for key in origin:
                    if key in plugin.dump_except_keys:
                        has_not_shown_keys = True
                    else:
                        dump[key] = origin[key]
            dump = pprint.pformat(dump, indent=4).split("\n")
            # dump = pprint.pformat(iodir.get(plugin, container=container), indent=4).split("\n")

            if plugin.dump_except_keys and has_not_shown_keys:
                keys = ", ".join(["`{}`".format(el) for el in plugin.dump_except_keys if el])
                prefix += "Keys not shown: {}\n".format(keys)

        counter = 0
        for el in paginate(dump,
                           prefix=prefix,
                           msg_prefix="```",
                           msg_suffix="```",
                           prefix_within_msg_prefix=False):
            counter += 1
            if counter > Config.get(self)["max_dump"]:
                await ctx.send("There are more data in dump which won't be shown.")
                return
            await ctx.send(el)

    @commands.command(name="storagedump", help="Dumps plugin storage", usage="<plugin name> [container]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_storagedump(self, ctx, name, container=None):
        await self._dump(ctx, Storage, "storage", name, container=container)

    @commands.command(name="configdump", help="Dumps plugin config", usage="<plugin name> [container]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_configdump(self, ctx, name, container=None):
        await self._dump(ctx, Config, "config", name, container=container)

    @commands.command(name="date", help="Current date and time")
    async def cmd_date(self, ctx):
        now = datetime.now()
        await ctx.send(now.strftime('%d.%m.%Y %H:%M:%S.%f'))

    @commands.command(name="debug", help="Print or change debug mode at runtime", usage="[true|on|off|false|toggle]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_debug(self, ctx, arg=None):
        toggle = None
        if arg is not None:
            arg = arg.lower()
        if arg == "toggle":
            toggle = not self.bot.DEBUG_MODE
        elif arg in ('on', 'true', 'set'):
            toggle = True
        elif arg in ('off', 'false'):
            toggle = False

        if toggle is None:
            if self.bot.DEBUG_MODE:
                await ctx.send("I am in debug mode.")
            else:
                await ctx.send("I am not in debug mode.")
        else:
            self.bot.set_debug_mode(toggle)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="livetickerkill", help="Kills all liveticker registrations")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_liveticker_kill(self, ctx):
        for src in self.bot.liveticker.registrations.values():
            for reg in list(src.values()):
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
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            await ctx.send(Lang.lang(self, "dm_empty_result", gbu(user)))
            return

        prefix = Lang.lang(self, "dm_result_prefix", gbu(user))
        for msg in paginate(msgs, prefix=prefix):
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            await ctx.send(msg)

    @commands.command(name="freedm")
    async def cmd_dmkill(self, ctx, reg_id: int):
        try:
            reg = self.bot.dm_listener.registrations[reg_id]
        except KeyError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        if reg.user != ctx.author and not is_botadmin(reg.user):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return

        await reg.kill()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
