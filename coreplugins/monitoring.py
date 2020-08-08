import pprint

from base import BasePlugin

from discord.ext import commands

from botutils import utils
from conf import Config


class Plugin(BasePlugin, name="Bot status commands for monitoring and debug purposes"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self)

    @commands.command(name="subsys", help="Shows registrations on subsystems")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def subsys(self, ctx):
        for msg in utils.paginate(self.bot.reaction_listener.callbacks,
                                  prefix="**Reactions registrations:**\n",
                                  suffix="\n"):
            await ctx.send(msg)
        for msg in utils.paginate(self.bot.timers.jobs,
                                  prefix="**Timer registrations:**\n",
                                  suffix="\n"):
            await ctx.send(msg)
        for msg in utils.paginate(self.bot.dm_listener.callbacks,
                                  prefix="**DM Listeners:**\n",
                                  suffix="\n"):
            await ctx.send(msg)

    @commands.command(name="pdump", help="Dumps plugin storage", usage="<plugin name>")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def configdump(self, ctx, name):
        plugin = utils.get_plugin_by_name(name)
        if plugin is None:
            await ctx.send("Plugin {} not found.".format(name))
            return
        await ctx.message.add_reaction(Config().CMDSUCCESS)

        dump = pprint.pformat(Config.get(plugin), indent=4).split("\n")
        for el in utils.paginate(dump):
            await ctx.send("```{}```".format(el))
