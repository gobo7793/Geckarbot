from discord.ext import commands

from botutils.utils import AsyncTimer


class Plugin(commands.Cog, name="Timer things"):

    def __init__(self, bot):
        self.bot = bot
        super(commands.Cog).__init__()
        bot.register(self)

    @commands.command(name="remindme", help="Reminds the author in x seconds.")
    async def reminder(self, ctx, duration):
        duration = int(duration)
        AsyncTimer(self.bot, duration, self.callback, ctx.message)
        await ctx.message.channel.send("Doing other things")

    async def callback(self, message):
        await message.channel.send("{} This is a reminder!".format(message.author.mention))
