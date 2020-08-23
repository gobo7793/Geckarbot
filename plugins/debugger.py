import sys

import discord
from discord.ext import commands
from discord.ext.commands import view
from discord.errors import HTTPException

from botutils import utils, converter
from subsystems.reactions import ReactionAddedEvent, ReactionRemovedEvent
from subsystems import help

from base import BasePlugin
from conf import Config, Lang


class Plugin(BasePlugin, name="Testing and debug things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.ADMIN)
        self.sleeper = None
        self.channel = None

    def default_storage(self):
        return {}

    def cog_check(self, ctx):
        role = discord.utils.get(ctx.author.roles, id=Config().BOTMASTER_ROLE_ID)
        if role is None:
            raise commands.MissingRole(Config().BOTMASTER_ROLE_ID)
        return True

    def wake_up_sync(self):
        self.bot.loop.create_task(self.wake_up())

    async def wake_up(self):
        await self.channel.send("I have been woken up!")

    @commands.command(name="sleep")
    async def sleep(self, ctx):
        self.channel = ctx.channel
        self.sleeper = self.bot.loop.call_later(sys.maxsize, print, "blub")
        await ctx.message.channel.send("Falling asleep.")
        # await self.sleeper
        # await ctx.message.channel.send("I was woken up!")

    @commands.command(name="awake")
    async def awake(self, ctx):
        self.sleeper.cancel()
        await ctx.message.channel.send("I'm waking myself up.")

    @commands.command(name="identify", help="calls utils.get_best_username")
    async def identify(self, ctx, *args):
        await ctx.channel.send("I will call you {}.".format(utils.get_best_username(ctx.message.author)))

    @commands.command(name="react")
    async def react(self, ctx, reaction):
        print(reaction)
        try:
            await ctx.message.add_reaction(reaction)
        except HTTPException:
            await ctx.message.add_reaction(Lang.CMDERROR)

    @staticmethod
    async def waitforreact_callback(event):
        msg = "PANIC!"
        if isinstance(event, ReactionAddedEvent):
            msg = "{}: You reacted on '{}' with {}!".format(utils.get_best_username(event.user),
                                                            event.message.content, event.emoji)
        if isinstance(event, ReactionRemovedEvent):
            msg = "{}: You took back your {} reaction on '{}'!".format(utils.get_best_username(event.user),
                                                                       event.message.content, event.emoji)
        await event.channel.send(msg)

    @commands.command(name="waitforreact")
    async def waitforreact(self, ctx):
        msg = await ctx.channel.send("React here pls")
        self.bot.reaction_listener.register(msg, self.waitforreact_callback)

    @commands.command(name="doerror")
    async def do_error(self, ctx):
        raise commands.CommandError("Testerror")

    @commands.command(name="writelogs")
    async def write_logs(self, ctx):
        await utils.log_to_admin_channel(ctx)
        await utils.write_debug_channel(self.bot, "writelogs used")

    @commands.command(name="mentionuser", help="Mentions a user, supports user cmd disabling.")
    async def mentionuser(self, ctx, user: discord.Member):
        if self.bot.ignoring.check_user_command(user, ctx.command.qualified_name):
            await ctx.send("Command blocked for user!")
        else:
            await ctx.send(user.mention)

    @commands.command(name="getemojiid", help="Gets the emoji ids to use in strings")
    async def get_emoji_id(self, ctx, emoji: discord.Emoji):
        str_rep = str(emoji).replace("<", "`").replace(">", "`")
        msg = await ctx.send(str_rep)
        await msg.add_reaction(emoji)

    @commands.command(name="dmme")
    async def dmme(self, ctx):
        await ctx.author.send("Here I aaaaam, this is meeee!")

    @staticmethod
    async def dmonreaction_callback(event):
        msg = "PANIC!"
        if isinstance(event, ReactionAddedEvent):
            msg = "You reacted on '{}' with {}!".format(event.message.content, event.emoji)
        if isinstance(event, ReactionRemovedEvent):
            msg = "You took back your {} reaction on '{}'!".format(event.message.content, event.emoji)
        await event.user.send(msg)

    @commands.command(name="dmonreaction")
    async def dmonreaction(self, ctx):
        msg = await ctx.channel.send("React here pls")
        self.bot.reaction_listener.register(msg, self.dmonreaction_callback)

    @commands.command(name="defaultstorage")
    async def defaultstorage(self, ctx, pluginname):
        plugin = converter.get_plugin_by_name(self.bot, pluginname)
        if plugin is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Plugin {} not found.".format(pluginname))
            return
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        await ctx.send("```{}```".format(plugin.default_storage()))

    @commands.command(name="libmod")
    async def libmod(self, ctx):
        await ctx.send(str(view._quotes))
        await ctx.send(str(view._all_quotes))

    @commands.command(name="cmdplugin")
    async def cmdplugin(self, ctx, *args):
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
