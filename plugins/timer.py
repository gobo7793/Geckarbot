import asyncio

from discord.ext import commands


class Plugin(commands.Cog, name="Timer things"):

    def __init__(self, bot):
        self.bot = bot
        super(commands.Cog).__init__()
        bot.register(self)

    async def timer(self, message, duration, callback):
        await asyncio.sleep(duration)
        await callback(message)

    @commands.command(name="remindme", help="Reminds the author in x seconds.")
    async def reminder(self, ctx, duration):
        duration = int(duration)
        await self.timer(ctx.message, duration, self.callback)
        await ctx.message.channel.send("Doing other things")

    async def callback(self, message):
        await message.channel.send("{} This is a reminder!".format(message.author.mention))
