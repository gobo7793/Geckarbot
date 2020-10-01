import random

import discord
from discord.ext import commands

from base import BasePlugin
from conf import Config, Storage, Lang
from botutils.permchecks import check_mod_access
from botutils.utils import add_reaction
from botutils.converters import get_best_username
from botutils.stringutils import paginate
from subsystems.help import DefaultCategories


class Plugin(BasePlugin, name="TIL"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category=DefaultCategories.MISC)
        self.can_reload = True

    def default_config(self):
        return {
            "manager": 0
        }

    def default_storage(self):
        return []

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.name))

    async def _manager_check(self, ctx, show_errors=True):
        """Checks if author is manager and returns False if not"""
        if ctx.author.id == Config.get(self)['manager'] or check_mod_access(ctx.author):
            return True

        if show_errors:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "must_manager"))
        return False

    @commands.group(name="til", invoke_without_command=True)
    async def til(self, ctx):
        if not Storage.get(self):
            await ctx.send(Lang.lang(self, "no_facts"))
            return
        ran_fact = random.choice(Storage.get(self))
        await ctx.send(ran_fact)

    @til.command(name="add")
    async def add(self, ctx, *, args):
        if await self._manager_check(ctx):
            Storage.get(self).append(args)
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @til.command(name="del")
    async def remove(self, ctx, fact_id: int):
        if await self._manager_check(ctx):
            fact_id -= 1
            if fact_id < 0 or fact_id >= len(Storage.get(self)):
                await ctx.send(Lang.lang(self, "invalid_id"))
                return

            del (Storage.get(self)[fact_id])
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @til.command(name="info")
    async def info(self, ctx):
        facts = []
        if await self._manager_check(ctx, show_errors=False) and isinstance(ctx.channel, discord.DMChannel):
            for i in range(len(Storage.get(self))):
                facts.append("#{}: {}".format(i + 1, Storage.get(self)[i]))

        manager = self.bot.guild.get_member(Config.get(self)['manager'])
        if manager is None:
            manager = self.bot.get_user(Config.get(self)['manager'])
        prefix = Lang.lang(self, "info_prefix", len(Storage.get(self)), get_best_username(manager))

        if facts:
            for msg in paginate(facts, prefix=prefix):
                await ctx.send(msg)
        else:
            await ctx.send(prefix)

    @til.command(name="manager")
    async def set_manger(self, ctx, user: discord.User):
        if await self._manager_check(ctx):
            Config.get(self)['manager'] = user.id
            Config.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
