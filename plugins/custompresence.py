from discord.ext import commands

from base import BasePlugin
from data import Lang
from botutils import utils
from botutils.stringutils import paginate
from subsystems.presence import PresencePriority


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

    @commands.group(name="presence", invoke_without_command=True)
    async def cmd_presence(self, ctx):
        await ctx.invoke(self.bot.get_command("presence list"))

    @cmd_presence.command(name="list")
    async def cmd_presence_list(self, ctx):
        def get_message(item):
            return Lang.lang(self, "presence_entry", item.presence_id, item.message)

        entries = self.bot.presence.filter_messages_list(PresencePriority.LOW)
        if not entries:
            await ctx.send(Lang.lang(self, "no_presences"))
        else:
            for msg in paginate(entries,
                                prefix=Lang.lang(self, "presence_prefix", len(entries)),
                                f=get_message):
                await ctx.send(msg)

    @cmd_presence.command(name="add")
    async def cmd_presence_add(self, ctx, *, message):
        if self.bot.presence.register(message, PresencePriority.LOW) is not None:
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, "presence_added_debug", message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_unknown_error"))

    @cmd_presence.command(name="del", usage="<id>")
    async def cmd_presence_del(self, ctx, entry_id: int):
        presence_message = "PANIC"
        if entry_id in self.bot.presence.messages:
            presence_message = self.bot.presence.messages[entry_id].message

        if self.bot.presence.deregister_id(entry_id):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, "presence_removed_debug", presence_message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_not_exists", entry_id))

    @cmd_presence.command(name="start", help="Starts the presence timer if it's not up", hidden=True)
    async def cmd_presence_start(self, ctx):
        if self.bot.presence.is_timer_up:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            return
        await self.bot.presence.start()
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_presence.command(name="skip")
    async def cmd_skip(self, ctx):
        await self.bot.presence._change_callback(self.bot.presence._timer_job)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
