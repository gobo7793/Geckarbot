from base import BasePlugin

from discord.ext import commands

from botutils.utils import paginate


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self)

    @commands.command(name="subsys", help="Shows registrations on subsystems")
    async def subsys(self, ctx):
        for msg in paginate(self.bot.reaction_listener.callbacks,
                            prefix="**Reactions registrations:**\n",
                            suffix="\n"):
            await ctx.send(msg)
        for msg in paginate(self.bot.timers.jobs,
                            prefix="**Timer registrations:**\n",
                            suffix="\n"):
            await ctx.send(msg)
        for msg in paginate(self.bot.dm_listener.callbacks,
                            prefix="**DM Listeners:**\n",
                            suffix="\n"):
            await ctx.send(msg)
