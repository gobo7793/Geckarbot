from discord.ext import commands

from botutils.utils import AsyncTimer, get_best_username


class Plugin(commands.Cog, name="Timer things"):

    def __init__(self, bot):
        self.bot = bot
        self.timers = {}
        super(commands.Cog).__init__()
        bot.register(self)

    def default_config(self):
        return {}

    @commands.command(name="remindme", help="Reminds the author in x seconds.")
    async def reminder(self, ctx, duration):
        if duration == "cancel":
            self.timers[ctx.message.author].cancel()
            return
        duration = int(duration)
        if ctx.message.author in self.timers:
            await ctx.message.channel.send("You already have a reminder.")
            return
        self.timers[ctx.message.author] = AsyncTimer(self.bot, duration, self.callback, ctx.message)
        await ctx.message.channel.send("Have fun doing other things. Don't panic, I will remind you in {} seconds.".format(duration))

    async def callback(self, message):
        await message.channel.send("{} This is a reminder!".format(message.author.mention))
        del self.timers[message.author]

    @commands.command(name="identify", help="calls utils.get_best_username")
    async def identify(self, ctx, *args):
        await ctx.channel.send("I will call you {}.".format(get_best_username(ctx.message.author)))
