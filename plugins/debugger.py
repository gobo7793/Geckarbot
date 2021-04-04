import sys
import asyncio
from typing import Union

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import utils, converters
from data import Config, Lang
from subsystems import timers
from subsystems.helpsys import DefaultCategories
from subsystems.ignoring import UserBlockedCommand
from subsystems.presence import PresencePriority


class Plugin(BasePlugin, name="Testing and debug things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super().__init__(bot)
        bot.register(self, DefaultCategories.ADMIN)
        self.sleeper = None
        self.channel = None

    def default_storage(self):
        return {}

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

    @commands.command(name="presencestart", help="Starts the presence timer", hidden=True)
    async def cmd_start_presence(self, ctx):
        if not self.bot.presence.is_timer_up:
            await self.bot.presence.start()
        else:
            await ctx.send("Timer already started")

    @commands.command(name="presencestop", help="Stops the presence timer in debug mode", hidden=True)
    async def cmd_stop_presence(self, ctx):
        if self.bot.presence.is_timer_up:
            self.bot.presence.stop()
        else:
            await ctx.send("Timer not started")

    @commands.command(name="presencenext", help="Sets the next presence message", hidden=True)
    async def cmd_next_presence(self, ctx):
        if self.bot.presence.is_timer_up:
            self.bot.presence.execute_change()
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
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
        self.channel = ctx.channel
        self.sleeper = self.bot.loop.call_later(sys.maxsize, print, "blub")
        await ctx.message.channel.send("Falling asleep.")

    @commands.command(name="awake", hidden=True)
    async def cmd_awake(self, ctx):
        self.sleeper.cancel()
        await ctx.message.channel.send("I'm waking myself up.")

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

    @staticmethod
    async def _spamcb(job):
        await job.data.send("Spam")

    # @commands.command(name="spam", hidden=True)
    async def cmd_spam(self, ctx):
        self.bot.timers.schedule(self._spamcb, timers.timedict(), data=ctx)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="tasks", hidden=True)
    async def cmd_tasklist(self, ctx):
        for el in asyncio.all_tasks():
            print(el)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="livetickersuche", hidden=True)
    async def cmd_livetickersuche(self, ctx, plugin=None, league=None):
        await ctx.send(self.bot.liveticker.search(plugin, league))
