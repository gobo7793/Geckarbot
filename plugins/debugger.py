import sys

import discord
from discord.ext import commands
from discord.errors import HTTPException
from botutils import utils
from subsystems.reactions import ReactionAddedEvent, ReactionRemovedEvent

from base import BasePlugin
from conf import Config


class Plugin(BasePlugin, name="Testing and debug things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super().__init__(bot)
        bot.register(self)
        self.sleeper = None
        self.channel = None

    def default_config(self):
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
            await ctx.message.add_reaction(Config().CMDERROR)

    @staticmethod
    async def waitforreact_callback(self, event):
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
