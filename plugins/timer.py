import sys

from discord.ext import commands
from botutils.utils import get_best_username
from subsystems.reactions import ReactionAddedEvent, ReactionRemovedEvent


from Geckarbot import BasePlugin


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
        await ctx.channel.send("I will call you {}.".format(get_best_username(ctx.message.author)))

    @commands.command(name="react")
    async def react(self, ctx, reaction):
        print(reaction)
        # print("available: {}".format(reaction.available))
        await ctx.message.add_reaction(reaction)
        print("usable: {}".format(reaction.usable()))

    async def waitforreact_callback(self, event):
        msg = "PANIC!"
        if isinstance(event, ReactionAddedEvent):
            msg = "{}: You reacted on '{}' with {}!".format(get_best_username(event.user),
                                                            event.message.content, event.emoji)
        if isinstance(event, ReactionRemovedEvent):
            msg = "{}: You took back your {} reaction on '{}'!".format(get_best_username(event.user),
                                                                       event.message.content, event.emoji)
        await event.channel.send(msg)

    @commands.command(name="waitforreact")
    async def waitforreact(self, ctx):
        msg = await ctx.channel.send("React here pls")
        self.bot.reaction_listener.register(msg, self.waitforreact_callback)
