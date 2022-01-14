from nextcord import User

from botutils.converters import get_best_username
from botutils.permchecks import check_mod_access
from botutils.utils import add_reaction
from base.data import Storage, Config, Lang
from plugins.spaetzle.utils import get_user_cell, get_user_league, UserNotFound


class UserBridge:
    """
    Subsystem for the connection between Discord users and Spaetzle participants

    :param plugin: links to the Spaetzle plugin
    """

    def __init__(self, plugin):
        self.plugin = plugin

    def get_user(self, ctx):
        """Returns the corresponding spaetzle participant to the message author"""
        if ctx.author.id in Storage().get(self.plugin)['discord_user_bridge']:
            return Storage().get(self.plugin)['discord_user_bridge'][ctx.author.id]
        return None

    def cut_bridge(self, ctx):
        """Cuts the connection of the message author to the noted Spaetzle participant"""
        user = ctx.author.id
        if user in Storage().get(self.plugin)["discord_user_bridge"]:
            del Storage().get(self.plugin)["discord_user_bridge"][user]
            Storage().save(self.plugin)
            return True
        return False

    def add_bridge(self, ctx, user):
        """Builds a connection between the message author and the Spaetzle participant"""
        try:
            get_user_cell(self.plugin, user)
            Storage().get(self.plugin)["discord_user_bridge"][ctx.message.author.id] = user
            Storage().save(self.plugin)
            return True
        except UserNotFound:
            return False


class Observed:
    """
    Subsystem for the selection of specific users for a closer view.

    :param plugin: links to the Spaetzle plugin
    """

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.users = Storage().get(plugin)['observed_users']

    def append(self, user: str) -> bool:
        """
        Adds the user to observation

        :param user: Spaetzle participant
        :return: success
        :raises UserNotFound: if the user is not a valid participant
        """
        try:
            get_user_league(self.plugin, user)
        except UserNotFound:
            return False

        if user not in self.users:
            self.users.append(user)
            Storage().save(self.plugin)
        return True

    def remove(self, user: str) -> bool:
        """
        Removes the user from observation

        :param user: Spaetzle participant
        :return: success
        """
        if user in self.users:
            self.users.remove(user)
            Storage().save(self.plugin)
            return True
        return False

    def get_all(self):
        return Storage().get(self.plugin)['observed_users']


class Trusted:
    """
    Subsystem for the role management in Spaetzle.

    :param plugin: links to the Spaetzle plugin
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.manager = Config().get(plugin)['manager']
        self.trusted = Config().get(plugin)['trusted']

    def get_trusted_ids(self):
        return self.trusted

    def get_trusted_names(self, bot):
        return [get_best_username(bot.get_user(x)) for x in self.trusted]

    def get_manager_ids(self):
        return self.manager

    def get_manager_names(self, bot):
        return [get_best_username(bot.get_user(x)) for x in self.manager]

    async def is_manager(self, ctx, show_error: bool = True) -> bool:
        """Returns whether the author of the message has the Manager role"""
        if ctx.author.id in self.manager:
            return True
        if show_error:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self.plugin, 'not_trusted'))
        return False

    async def is_trusted(self, ctx, show_error: bool = True) -> bool:
        """Returns whether the author of the message has the Trusted or Manager role"""
        if ctx.author.id in self.trusted + self.manager:
            return True
        if show_error:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self.plugin, 'not_trusted'))
        return False

    async def add(self, role: list, ctx, user: User):
        """
        Adds a user to the trusted or manager role

        :param role: List of the role members
        :param ctx: ctx from command
        :param user: discord User
        """
        if await self.is_manager(ctx, show_error=False) or check_mod_access(ctx.author):
            if user.id not in role:
                role.append(user.id)
            Config().save(self.plugin)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)

    async def add_manager(self, ctx, user: User):
        await self.add(self.manager, ctx, user)

    async def add_trusted(self, ctx, user: User):
        await self.add(self.trusted, ctx, user)

    async def remove(self, role: list, ctx, user: User):
        """
        Removes a user from the trusted or manager role

        :param role: List of the role members
        :param ctx: ctx from command
        :param user: discord User
        """
        if await self.is_manager(ctx, show_error=False) or check_mod_access(ctx.author):
            if user.id in role:
                role.remove(user.id)
            Config().save(self.plugin)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)

    async def remove_manager(self, ctx, user: User):
        await self.remove(self.manager, ctx, user)

    async def remove_trusted(self, ctx, user: User):
        await self.remove(self.trusted, ctx, user)
