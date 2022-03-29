from nextcord import ChannelType, TextChannel, Thread, Embed
from nextcord.ext import commands
from nextcord.ext.commands import Context

from base.configurable import BasePlugin
from base.data import Config, Lang
from botutils import utils
from botutils.converters import get_best_username
from botutils.timeutils import to_unix_str
from botutils.utils import add_reaction
from services.helpsys import DefaultCategories


class Plugin(BasePlugin, name="Threads"):

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.MISC)

    def command_help_string(self, command):
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

    async def limit_to_bot_threads(self, ctx: Context) -> bool:
        """
        Limits a command to threads owned by the bot. Sends a message with a note else.

        :param ctx: Discord Context
        :return: True if owned by bot, False else
        """
        if not isinstance(ctx.channel, Thread):
            await ctx.send(Lang.lang(self, "channel_not_thread"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return False
        if ctx.channel.owner != self.bot.user:
            await ctx.send(Lang.lang(self, "thread_not_owned"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return False
        return True

    @commands.group(name="thread")
    async def cmd_thread(self, ctx: Context):
        if ctx.invoked_subcommand is not None:
            return
        channel = ctx.channel
        if isinstance(channel, Thread):
            channel = channel.parent
        threads_msg = [f"{t.mention} ({get_best_username(t.owner)})" for t in channel.threads if not t.locked]
        async for t in ctx.channel.archived_threads(limit=2):
            if t.locked:
                continue
            threads_msg.append(f"🧓 {t.mention} ({get_best_username(t.owner)}, {to_unix_str(t.archive_timestamp)})")
        if threads_msg:
            await ctx.send(embed=Embed(title=Lang.lang(self, 'thread_list', channel.name),
                                       description="\n".join(threads_msg)))
        else:
            await ctx.send(Lang.lang(self, 'no_thread_list'))

    @cmd_thread.command(name="open")
    async def cmd_thread_open(self, ctx: Context, title: str):
        channel = ctx.channel
        if isinstance(channel, Thread):
            channel = channel.parent
        if not isinstance(channel, TextChannel):
            await ctx.send(Lang.lang(self, "open_unable"))
            return
        thread = await channel.create_thread(name=title, type=ChannelType.public_thread)
        await thread.send("👋")
        await thread.add_user(ctx.author)

    @cmd_thread.command(name="archive")
    async def cmd_thread_delete(self, ctx: Context):
        if not self.limit_to_bot_threads(ctx):
            return
        await ctx.channel.edit(archived=True)

    @cmd_thread.command(name="pin")
    async def cmd_thread_pin(self, ctx: Context):
        if not ctx.channel.permissions_for(ctx.me).manage_threads:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
        if not await self.limit_to_bot_threads(ctx):
            return
        if not ctx.message.reference:
            await ctx.send(Lang.lang(self, "pin_no_reply"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        if not ctx.message.reference.resolved:
            await ctx.send(Lang.lang(self, "pin_err"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        await ctx.message.reference.resolved.pin()