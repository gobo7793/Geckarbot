from typing import Union

import discord
from discord.ext import commands
from discord.ext.commands import CheckFailure

from data import Config


class WrongChannel(CheckFailure):
    """
    Will be raised if a command is executed in a channel in which the command is not allowed.
    """

    def __init__(self, channel: Union[str, int]):
        """
        Creates a new WrongChannel instance

        :param channel: Channel in which the command can be executed
        """
        self.channel = channel
        super().__init__()


def in_channel(channel_id):
    """
    Check if CMD can be used in the channel with given channel id.
    Can be used as command check function in decorators.
    """

    def predicate(ctx):
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        is_group = isinstance(ctx.channel, discord.GroupChannel)
        is_id = ctx.channel.id == channel_id
        if is_dm or is_group or is_id:
            return True
        raise WrongChannel(channel_id)

    return commands.check(predicate)


def _check_access(user: discord.User, roles):
    """Performs the access check if a user has any of the given roles"""
    if not isinstance(user, discord.Member):
        user = discord.utils.get(Config().bot.guild.members, id=user.id)
    if user is None:
        return False
    for role in user.roles:
        if role.id in roles:
            return True
    return False


def check_admin_access(user: discord.User):
    """
    Checks if the user has admin access to bot commands. If you can, use
    `@commands.has_any_role(*Config().ADMIN_ROLES)` instead.
    """
    return _check_access(user, Config().ADMIN_ROLES)


def check_mod_access(user: discord.User):
    """
    Checks if the user has mod access to bot commands. If you can, use
    `@commands.has_any_role(*Config().MOD_ROLES)` instead.
    """
    return _check_access(user, Config().MOD_ROLES)


def is_botadmin(user: discord.User):
    """
    Checks if the user has bot admin role.
    """
    return _check_access(user, [Config().BOT_ADMIN_ROLE_ID])


def debug_user_check_id(user_id: int):
    """
    Checks if the given user can use the bot based on the debug users list.
    Note: The debug users list is active only if the list is not empty and debug mode is enabled.

    :param user_id: The user id to check
    :returns: If debug mode is disabled: True.
              If debug mode is enabled: False if user is not permitted to use the bot, otherwise True.
    """
    if (Config().bot.DEBUG_MODE and Config().bot.DEBUG_USERS
            and user_id not in Config().bot.DEBUG_USERS):
        return False
    return True


def debug_user_check(user: discord.User):
    """
    Checks if the given user can use the bot based on the debug users list.
    Note: The debug users list is active only if debug mode is enabled.

    :param user: The user to check
    :returns: If debug mode is disabled: True.
              If debug mode is enabled: True only if User is on debug whitelist, else False.
    """
    return debug_user_check_id(user.id)
