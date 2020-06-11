from discord.ext import commands

from botutils.utils import AsyncTimer, get_best_username

from Geckarbot import BasePlugin


class Plugin(BasePlugin, name="Timer things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super().__init__(bot)
        bot.register(self)

    def default_config(self):
        return {}

    @commands.command(name="remindme", help="Reminds the author in x seconds.")
    async def reminder(self, ctx, duration):
        if duration == "cancel":
            self.timers[ctx.msg_link.author].cancel()
            return
        duration = int(duration)
        if ctx.msg_link.author in self.timers:
            await ctx.msg_link.channel.send("You already have a reminder.")
            return
        self.timers[ctx.msg_link.author] = AsyncTimer(self.bot, duration, self.callback, ctx.msg_link)
        await ctx.msg_link.channel.send("Have fun doing other things. Don't panic, I will remind you in {} seconds.".format(duration))

    async def callback(self, message):
        await message.channel.send("{} This is a reminder!".format(message.author.mention))
        del self.timers[message.author]

    @commands.command(name="identify", help="calls utils.get_best_username")
    async def identify(self, ctx, *args):
        await ctx.channel.send("I will call you {}.".format(get_best_username(ctx.msg_link.author)))
