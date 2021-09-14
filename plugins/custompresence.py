import re

from discord.ext import commands

from base.configurable import BasePlugin
from data import Lang
from botutils import utils
from botutils.stringutils import paginate
from services.presence import PresencePriority, activitymap
from services.helpsys import DefaultCategories


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, DefaultCategories.USER)

    def command_help_string(self, command):
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

    @commands.group(name="presence", invoke_without_command=True)
    async def cmd_presence(self, ctx):
        await ctx.invoke(self.bot.get_command("presence list"))

    @cmd_presence.command(name="list")
    async def cmd_presence_list(self, ctx):
        def get_message(item):
            return Lang.lang(self, "presence_entry", item.presence_id, item.activity, item.message)

        entries = self.bot.presence.filter_messages_list(PresencePriority.LOW)
        if not entries:
            await ctx.send(Lang.lang(self, "no_presences"))
        else:
            for msg in paginate(entries,
                                prefix=Lang.lang(self, "presence_prefix", len(entries)),
                                f=get_message):
                await ctx.send(msg)

    @cmd_presence.command(name="add", usage="[playing|listening|watching|streaming|competing]")
    async def cmd_presence_add(self, ctx, ptype_arg=None):
        if ptype_arg is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return

        # parse args
        if ptype_arg not in activitymap:
            ptype_arg = ""
            ptype = "playing"
        else:
            ptype = ptype_arg
        message = re.search(r"presence\s+add\s+{}\s*(.*)".format(ptype_arg), ctx.message.content)
        if message is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("This should not happen.")
            return
        message = message.groups()[0].strip()
        if not message:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return

        # register
        if self.bot.presence.register(message, activity=ptype, priority=PresencePriority.LOW) is not None:
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
            await utils.add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return
        await self.bot.presence.start()
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_presence.command(name="skip")
    async def cmd_skip(self, ctx):
        try:
            await self.bot.presence.skip()
        except RuntimeError:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send("Presence timer is not up.")
            return
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
