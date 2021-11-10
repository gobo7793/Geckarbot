import pprint
from datetime import datetime
from typing import Union

import discord
from discord.ext import commands

from base.configurable import BasePlugin, ConfigurableType
from base.data import Storage, Config, Lang
from botutils import converters
from botutils.permchecks import is_botadmin
from botutils.stringutils import paginate
from botutils.converters import get_best_username as gbu
from botutils.utils import add_reaction, write_debug_channel
from services.helpsys import DefaultCategories


async def cmd_del_event(msg, title_suffix):
    """
    Prints info about a message if it contained a cmd. Used by edit/delete events.

    :param msg: message before edit or delete
    :param title_suffix: "deletion" or "edit", appended to title
    :return:
    """
    if msg.content.startswith("!"):
        event_name = "Command " + title_suffix
    elif msg.content.startswith("+"):
        event_name = "Custom command " + title_suffix
    else:
        return
    e = discord.Embed()
    e.add_field(name="Event", value=event_name)
    e.add_field(name="Author", value=gbu(msg.author))
    e.add_field(name="Command", value=msg.content)
    e.add_field(name="Channel", value=msg.channel)
    await write_debug_channel(e)


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self):
        self.bot = Config().bot
        super().__init__()
        self.bot.register(self, DefaultCategories.ADMIN)

        # Write cmd deletions/edits to debug chan
        @self.bot.event
        async def on_message_edit(before, after):
            if before.content != after.content:
                await cmd_del_event(before, "edit")

        @self.bot.event
        async def on_message_delete(msg):
            await cmd_del_event(msg, "deletion")

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    def default_config(self, container=None):
        return {
            'max_dump': 4  # maximum storage/configdump messages to show
        }

    @commands.command(name="subsys", hidden=True)
    async def cmd_subsys(self, ctx):
        await ctx.send("Did you mean: `!service`")

    @commands.command(name="service", aliases=["services"], help="Shows registrations on services",
                      description="Shows registrations on services. If a service name is given, "
                                  "only registrations for this service will be shown.",
                      usage="[dmlisteners|ignoring|liveticker|presence|reactions|timers]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_service(self, ctx, subsystem=""):
        if not subsystem or subsystem == "reactions":
            reaction_prefix = "**{} Reactions registrations:**\n".format(len(self.bot.reaction_listener.registrations))
            for msg in paginate(self.bot.reaction_listener.registrations,
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
            minutes = []
            match_timer = self.bot.liveticker.match_timer
            if match_timer:
                minutes = match_timer.timedict.get("minute")
            liveticker_list = [f"Liveticker minutes: {minutes}", "**LeagueRegistrations:**"]
            l_reg_lines = [f"{l_reg.league}: {l_reg}" for l_reg in self.bot.liveticker.league_regs.values()]
            liveticker_list.extend(l_reg_lines)
            if not l_reg_lines:
                liveticker_list.append("None")
            liveticker_list.append("**CoroRegistrations:**")
            c_reg_lines = [f"{c_reg.id}: {c_reg}" for c_reg in self.bot.liveticker.coro_regs.values()]
            liveticker_list.extend(c_reg_lines)
            if not c_reg_lines:
                liveticker_list.append("None")

            for msg in paginate(liveticker_list,
                                prefix="**Liveticker Registrations:**\n",
                                suffix="\n",
                                if_empty="None"):
                await ctx.send(msg)

    async def _dump(self, ctx, iodir, name, container=None):
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
        await self._dump(ctx, Storage, name, container=container)

    @commands.command(name="configdump", help="Dumps plugin config", usage="<plugin name> [container]")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_configdump(self, ctx, name, container=None):
        await self._dump(ctx, Config, name, container=container)

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
        for _, _, c_reg in list(self.bot.liveticker.search_coro()):
            await c_reg.deregister()
        for src in Storage().get(self.bot.liveticker)['registrations']:
            Storage().get(self.bot.liveticker)['registrations'][src] = {}
        Storage().save(self.bot.liveticker)
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
