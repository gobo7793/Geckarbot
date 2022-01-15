from nextcord import ChannelType, TextChannel, Thread
from nextcord.ext import commands
from nextcord.ext.commands import Context

from base.configurable import BasePlugin
from base.data import Config, Lang
from services.helpsys import DefaultCategories


class Plugin(BasePlugin, name="Threads"):

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.MISC)

    @commands.group(name="thread")
    async def cmd_thread(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.cmd_thread)

    @cmd_thread.command(name="open")
    async def cmd_thread_open(self, ctx: Context, title: str):
        channel = ctx.channel
        if isinstance(channel, Thread):
            channel = channel.parent
        if not isinstance(channel, TextChannel):
            await ctx.send(Lang.lang(self, "open_unable"))
            return
        thread = await ctx.channel.create_thread(name=title, type=ChannelType.public_thread)
        await thread.send("👋")
        await thread.add_user(ctx.author)

    @cmd_thread.command(name="archive")
    async def cmd_thread_delete(self, ctx: Context):
        if not isinstance(ctx.channel, Thread) or ctx.channel.owner != self.bot.user:
            return
        await ctx.channel.edit(archived=True)