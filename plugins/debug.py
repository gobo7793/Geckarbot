import asyncio
from typing import Union, Optional
from datetime import datetime

import discord
from discord.ext import commands

from base.configurable import BasePlugin
from botutils import utils, converters, setter, stringutils
from botutils.timeutils import to_unix_str, TimestampStyle
from botutils.utils import execute_anything_sync, add_reaction
from data import Config, Lang
from services.helpsys import DefaultCategories
from services.ignoring import UserBlockedCommand
from services.presence import PresencePriority
from services.timers import timedict_by_datetime, Job


class Plugin(BasePlugin, name="Testing and debug things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super().__init__(bot)
        bot.register(self, DefaultCategories.ADMIN)
        self.sleeper = None
        self.channel = None

        whitelist = {
            "switch1_a": [bool, True],
            "switch1_b": [bool, False],
            "switch1_c": [bool, False],
            "switch2_a": [bool, False],
            "switch2_b": [bool, True],
            "p": [int, 4],
            "msg": [str, "foo"],
            "channelid": [discord.TextChannel, None],
            "memberid": [discord.Member, None],
            "userid": [discord.User, None],
            "roleid": [discord.Role, None],
        }
        desc = {
            "msg": "Message thingy",
            "switch2_b": "Switch!"
        }
        self.setter = setter.ConfigSetter(self, whitelist, desc)
        self.setter.add_switch("switch1_a", "switch1_b", "switch1_c")
        self.setter.add_switch("switch2_a", "switch2_b")
        self.sleeptask = None
        self.recsleeptask = None
        self.spamjob = None

    def default_storage(self, container=None):
        return {}

    def default_config(self, container=None):
        return {
            "version": 1,
            "switch1_a": True,
            "switch1_b": False,
            "switch1_c": False,
            "switch2_a": False,
            "switch2_b": True,
            "p": 4,
        }

    def cog_check(self, ctx):
        role = discord.utils.get(ctx.author.roles, id=Config().BOT_ADMIN_ROLE_ID)
        if role is None:
            raise commands.MissingRole(Config().BOT_ADMIN_ROLE_ID)
        return True

    # Maybe really useful debugging commands

    @commands.command(name="getemojiid", help="Gets the emoji ids to use in strings", hidden=True)
    async def cmd_get_emoji_id(self, ctx, emoji: discord.Emoji):
        str_rep = str(emoji).replace("<", "`").replace(">", "`")
        msg = await ctx.send(str_rep)
        await utils.add_reaction(msg, emoji)

    @commands.command(name="defaultstorage", hidden=True)
    async def cmd_defaultstorage(self, ctx, pluginname):
        plugin = converters.get_plugin_by_name(pluginname)
        if plugin is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("Plugin {} not found.".format(pluginname))
            return
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send("```{}```".format(plugin.default_storage()))

    @commands.command(name="cmdplugin", hidden=True)
    async def cmd_plugin(self, ctx, *args):
        for plugin in self.bot.plugins:
            if not isinstance(plugin.instance, BasePlugin):
                continue
            print("=======")
            print("plugin: " + plugin.name)
            for cmd in plugin.instance.get_commands():
                print("  cmd name: {}".format(cmd.name))
                print("    qualified name: " + cmd.qualified_name)
                print("    signature: " + cmd.signature)
                print("    parents: " + str(cmd.parents))
                print("    help: " + str(cmd.help))
                print("    description: " + str(cmd.description))
                print("    brief: " + str(cmd.brief))
                print("    usage: " + str(cmd.usage))

    @commands.command(name="presenceadd", help="Adds presence messages", hidden=True)
    async def cmd_add_presence(self, ctx, prio, *, message):
        if prio.lower() == "low":
            priority = PresencePriority.LOW
        elif prio.lower() == "default":
            priority = PresencePriority.DEFAULT
        elif prio.lower() == "high":
            priority = PresencePriority.HIGH
        else:
            raise commands.BadArgument("prio must be low, default or high")

        new_id = self.bot.presence.register(message, priority)
        await ctx.send("registered with result {}".format(new_id))

    @commands.command(name="presencedel", help="Removes presence messages, with raw IDs", hidden=True)
    async def cmd_del_presence(self, ctx, presence_id: int):
        result = self.bot.presence.deregister_id(presence_id)
        await ctx.send("deregistered with result {}".format(result))

    @commands.command(name="presencestop", help="Stops the presence timer in debug mode", hidden=True)
    async def cmd_stop_presence(self, ctx):
        if self.bot.presence.is_timer_up:
            self.bot.presence.stop()
        else:
            await ctx.send("Timer not started")

    @commands.command(name="write", hidden=True)
    async def cmd_write(self, ctx, *, args):
        await ctx.send(args)

    # Testing commands
    @commands.command(name="mentionuser", help="Mentions a user, supports user cmd disabling.", hidden=True)
    async def cmd_mentionuser(self, ctx, user: discord.Member):
        if self.bot.ignoring.check_passive_usage(user, ctx.command.qualified_name):
            raise UserBlockedCommand(user, ctx.command.qualified_name)
        await ctx.send(user.mention)

    @commands.command(name="sleep", hidden=True)
    async def cmd_sleep(self, ctx):
        if self.sleeptask is not None and not self.sleeptask.cancelled() and not self.sleeptask.done():
            await ctx.send("Already sleeping. Sorry, there is only one bed.")
            return

        self.channel = ctx.channel
        self.sleeper = asyncio.Lock()
        self.sleeptask = asyncio.current_task()
        await self.sleeper.acquire()
        await ctx.send("Falling asleep.")
        async with self.sleeper:
            await ctx.send("Waking up! Yay!")

        # cleanup
        self.sleeper = None

    @commands.command(name="awake", hidden=True)
    async def cmd_awake(self, ctx):
        if self.sleeper is None:
            await ctx.send("Nothing to wake up.")
            return
        await ctx.message.channel.send("I'm waking myself up.")
        self.sleeper.release()
        self.sleeper = None

    @commands.command(name="sleepkill", hidden=True)
    async def cmd_sleepkill(self, ctx):
        if self.sleeptask is None:
            await ctx.send("Nothing to kill yet.")
            return
        if self.sleeptask.cancelled():
            await ctx.send("Sleeper task was killed. Nothing to do.")
            if self.sleeptask.done():
                await ctx.send("Also done btw.")
            return
        if self.sleeptask.done():
            await ctx.send("Sleeper task is done. Nothing to do.")
            return
        self.sleeptask.cancel()
        self.sleeper = None
        await ctx.send("Sleeper was killed in cold blood.")

    @commands.command(name="identify", help="calls converters.get_best_username", hidden=True)
    async def cmd_identify(self, ctx, *args):
        await ctx.channel.send("I will call you {}.".format(converters.get_best_username(ctx.message.author)))

    @commands.command(name="react", hidden=True)
    async def cmd_react(self, ctx, reaction):
        print(reaction)
        await utils.add_reaction(ctx.message, reaction)

    @commands.command(name="doerror", hidden=True)
    async def cmd_do_error(self, ctx):
        raise commands.CommandError("Testerror")

    @staticmethod
    async def error_cb(job: Optional[Job] = None):
        """
        Raises an exception.

        :param job: sends a msg to job.data
        """
        if job:
            await job.data.send("Bang! Bang!")
        raise Exception("Bang! Bang!")

    @commands.command(name="timererror", hidden=True)
    async def cmd_timer_error(self, ctx):
        now = datetime.now()
        td = {
            "year": now.year,
            "month": now.month,
            "monthday": now.day,
            "hour": now.hour,
            "minute": now.minute + 1
        }
        self.bot.timers.schedule(self.error_cb, td, data=ctx)
        await ctx.send(str(td))
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="writelogs", hidden=True)
    async def cmd_write_logs(self, ctx):
        await utils.log_to_admin_channel(ctx)
        await utils.log_to_mod_channel(ctx)
        await utils.write_debug_channel("writelogs used")

    @commands.command(name="pingme", hidden=True)
    async def cmd_pingme(self, ctx, user: Union[discord.Member, discord.User, str]):
        if isinstance(user, (discord.User, discord.Member)):
            await ctx.send("{}".format(user.mention))
        else:
            await ctx.send("Sorry, no user found for {}".format(user))

    @commands.command(name="tasks", hidden=True)
    async def cmd_tasklist(self, ctx):
        for el in asyncio.all_tasks():
            print(el)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="livetickersuche", hidden=True)
    async def cmd_livetickersuche(self, ctx, plugin=None, source=None, league=None):
        await ctx.send(self.bot.liveticker.search(plugin=plugin, league=league, source=source))

    @staticmethod
    async def incr(ctx, i):
        await ctx.send(str(i + 1))
        return i + 1

    @staticmethod
    def increment(i):
        return i + 1

    @commands.command(name="exec", hidden=True)
    async def cmd_execute_anything(self, ctx):
        i = 0
        await ctx.send("coro function")
        i = await utils.execute_anything(self.incr, ctx, i)

        await ctx.send("coro")
        i = await utils.execute_anything(self.incr(ctx, i))

        await ctx.send("function")
        i = await utils.execute_anything(self.increment, i)
        await ctx.send(str(i))

    @commands.command(name="syncexec", hidden=True)
    async def cmd_execute_anything_sync(self, ctx):
        i = 0
        await ctx.send("coro function")
        utils.execute_anything_sync(self.incr, ctx, i)
        i += 1

        await ctx.send("coro")
        utils.execute_anything_sync(self.incr(ctx, i))
        i += 1

        await ctx.send("function")
        i = utils.execute_anything_sync(self.increment, i)
        await ctx.send(str(i))

    @commands.command(name="listdemo", hidden=True)
    async def cmd_list(self, ctx):
        await self.setter.list(ctx)

    @commands.command(name="setdemo", hidden=True)
    async def cmd_set(self, ctx, key, value=None):
        await self.setter.set_cmd(ctx, key, value)

    @commands.group(name="qname", hidden=True)
    async def cmd_qname(self, ctx):
        await ctx.send(ctx.command.qualified_name)

    @cmd_qname.command(name="sub", hidden=True)
    async def cmd_qname_sub(self, ctx):
        await ctx.send(ctx.command.qualified_name)

    @commands.command(name="rolebyid", hidden=True)
    async def cmd_rolebyid(self, ctx, rid: int):
        role = self.bot.guild.get_role(rid)
        await ctx.send(role.mention)

    @commands.command(name="rolebymention", hidden=True)
    async def cmd_rolebymention(self, ctx, role: discord.Role):
        # role = await commands.RoleConverter().convert(ctx, role)
        await ctx.send(role.mention)

    @commands.command(name="timersinfo", hidden=True)
    async def cmd_debugtimers(self, ctx):
        # pylint: disable=protected-access
        msgs = []
        for i in range(len(self.bot.timers.jobs)):
            job = self.bot.timers.jobs[i]
            msgs.append("")
            msgs.append("**#{}:**".format(i))
            msgs.append("  **td:** {}".format(job._timedict))
            msgs.append("  **coro:** {}".format(job._coro))
            msgs.append("  **lock is locked:** {}".format(job._lock.locked()))
            msgs.append("  **is scheduled:** {}".format(job._is_scheduled))
            msgs.append("  **cancelled:** {}".format(job._cancelled))
            msgs.append("  **last exec:** {}".format(job._last_exec))
            msgs.append("  **task:** {}".format(job._task))
            msgs.append("  **task done:** {}".format(job._task.done()))

        for msg in stringutils.paginate(msgs):
            await ctx.send(msg)

    @staticmethod
    async def spam_cb(job):
        await job.data.send("SPAM")

    # @commands.command(name="spam", hidden=True)
    async def cmd_spam(self, ctx):
        td = {"minute": list(range(60))}
        self.bot.timers.schedule(self.spam_cb, td, data=ctx)

    @commands.command(name="execerror", hidden=True)
    async def cmd_execerror(self, ctx):
        execute_anything_sync(self.error_cb)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="unix")
    async def cmd_unix(self, ctx):
        msg = []
        for style in TimestampStyle:
            msg.append(f"{style}: {to_unix_str(timestamp=datetime.now(), style=style)}")
        await ctx.send("\n".join(msg))
    
    @staticmethod
    async def timerexec_cb(job):
        await job.data.send("blub")

    @commands.command(name="timerexec", hidden=True)
    async def cmd_timerexec(self, ctx):
        self.channel = ctx.channel
        td = timedict_by_datetime(datetime.now())
        job = self.bot.timers.schedule(self.timerexec_cb, td, data=ctx)
        job.execute()
