import asyncio
import random
import logging
import re

from nextcord import User, DMChannel
from nextcord.ext import commands

from base.configurable import BasePlugin, NotFound
from base.data import Config, Storage, Lang
from botutils.setter import ConfigSetter
from botutils.permchecks import check_mod_access
from botutils.utils import add_reaction, helpstring_helper, execute_anything_sync
from botutils.converters import get_best_username
from botutils.stringutils import paginate
from services.helpsys import DefaultCategories
from services.reactions import ReactionAddedEvent, BaseReactionEvent


class Plugin(BasePlugin, name="TIL"):
    """Provides custom cmds"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category=DefaultCategories.MISC)
        self.can_reload = True
        self.logger = logging.getLogger(__name__)

        self.basecfg = {
            "allow_search": [bool, True],
            "redo_cooldown": [int, 5],
            "cooldown_message": [bool, True],
        }
        self.config_setter = ConfigSetter(self, self.basecfg)

        # redo state handling
        self.redo_emoji = Lang.lang(self, "redo_emoji")
        self.redo_last_msg = None
        self.redo_registration = None

    def default_config(self, container=None):
        return {
            "manager": 0
        }

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
        return []

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    async def _manager_check(self, ctx, show_errors=True):
        """Checks if author is manager and returns False if not"""
        if ctx.author.id == Config.get(self)['manager'] or check_mod_access(ctx.author):
            return True

        if show_errors:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "must_manager"))
        return False

    def cleanup_redo_reaction(self):
        """
        Removes the redo reaction, deregisters the listener and resets the redo-specific plugin state
        """
        if self.redo_registration:
            self.redo_registration.deregister()
            self.redo_registration = None
        if self.redo_last_msg:
            # avoid await to gracefully skip exceptions
            execute_anything_sync(self.redo_last_msg.remove_reaction(self.redo_emoji, self.bot.user))
            self.redo_last_msg = None

    async def redo_cb(self, event: BaseReactionEvent):
        """
        Called by reaction listener to handle redo reactions

        :param event: ReactionEvent
        """
        if not isinstance(event, ReactionAddedEvent) \
                or str(event.emoji) != self.redo_emoji \
                or event.user == self.bot.user:
            return

        self.logger.debug("TIL redo reaction caught")
        if self.redo_registration:
            chan = self.redo_last_msg.channel
            self.cleanup_redo_reaction()
            await self._send_til(chan)

    async def _setup_redo_reaction(self, newmsg):
        self.cleanup_redo_reaction()

        # Setup
        self.redo_last_msg = newmsg
        self.redo_registration = self.bot.reaction_listener.register(newmsg, self.redo_cb)
        await add_reaction(newmsg, self.redo_emoji)

    async def _send_til(self, channel):
        self.logger.debug("Sending til to %s", str(channel))
        if not Storage.get(self):
            await channel.send(Lang.lang(self, "no_facts"))
            return
        ran_fact = random.choice(Storage.get(self))
        msg = await channel.send(ran_fact)

        cd = self.config_setter.get_config("redo_cooldown")
        if cd > 0:
            await asyncio.sleep(cd)
        await self._setup_redo_reaction(msg)

    @commands.group(name="til", invoke_without_command=True)
    async def cmd_til(self, ctx):
        await self._send_til(ctx.channel)

    @cmd_til.command(name="add")
    async def cmd_add(self, ctx, *, args):
        if await self._manager_check(ctx):
            Storage.get(self).append(args)
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_til.command(name="del")
    async def cmd_remove(self, ctx, fact_id: int):
        if await self._manager_check(ctx):
            fact_id -= 1
            if fact_id < 0 or fact_id >= len(Storage.get(self)):
                await ctx.send(Lang.lang(self, "invalid_id"))
                return

            del Storage.get(self)[fact_id]
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_til.command(name="info")
    async def cmd_info(self, ctx):
        facts = []
        if await self._manager_check(ctx, show_errors=False) and isinstance(ctx.channel, DMChannel):
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

    @cmd_til.command(name="search")
    async def cmd_search(self, ctx, *searchterms):
        if not self.config_setter.get_config("allow_search") and \
                not await self._manager_check(ctx, show_errors=False) and not check_mod_access(ctx.author):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return

        # Search for candidates
        best_til, best_score = None, 0
        for til in Storage.get(self):
            candidate = til.lower()
            matches = 0
            found = True
            for term in searchterms:
                found = len(re.findall(term.lower(), candidate))
                if not found:
                    break
                matches += found

            if not found:
                continue

            if matches > best_score:
                best_til = til
                best_score = matches

        # Send result
        if best_til is None:
            await ctx.send(Lang.lang(self, "search_empty_result", " ".join(searchterms)))
            return

        await ctx.send(best_til)

    @cmd_til.command(name="set", aliases=["config"])
    async def cmd_set(self, ctx, key=None, value=None):
        if not await self._manager_check(ctx, show_errors=False) and not check_mod_access(ctx.author):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return

        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        await self.config_setter.set_cmd(ctx, key, value)

    @cmd_til.command(name="manager")
    async def cmd_set_manger(self, ctx, user: User):
        if await self._manager_check(ctx):
            Config.get(self)['manager'] = user.id
            Config.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
