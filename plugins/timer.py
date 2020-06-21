import asyncio
import sys
import logging

from discord.ext import commands
from botutils.utils import AsyncTimer, get_best_username
from subsystems.reactions import ReactionAddedEvent, ReactionRemovedEvent
from subsystems.timers import timedict
import discord

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

    @commands.command(name="remindme", help="Reminds the author in x seconds.",
                      description="Reminds the author in x seconds. "
                                  "The duration can be set with trailing s for seconds, m for minutes or h for hours. "
                                  "Examples: 5s = 5 seconds, 5m = 5 minutes, 5h = 5 hours.")
    async def reminder(self, ctx, duration, *message):
        sec_multiplicator = 1
        timespan_unit = "seconds"

        if duration == "cancel":
            self.timers[ctx.message.author].cancel()
            return
        elif duration.endswith("s"):
            duration = duration[:-1]
        elif duration.endswith("m"):
            duration = duration[:-1]
            sec_multiplicator = 60
            timespan_unit = "minutes"
        elif duration.endswith("h"):
            duration = duration[:-1]
            sec_multiplicator = 3600
            timespan_unit = "hours"

        timespan = int(duration) * sec_multiplicator
        if ctx.message.author in self.timers:
            await ctx.message.channel.send("You already have a reminder.")
            return
        self.timers[ctx.message.author] = AsyncTimer(self.bot, timespan, self.reminder_callback, ctx.message, " ".join(message))
        await ctx.message.channel.send(
            "I will remind you in {} {}.".format(duration, timespan_unit))

    async def reminder_callback(self, message, remindtext):
        await message.channel.send("{} This is a reminder for {}!".format(message.author.mention, remindtext))
        del self.timers[message.author]

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
