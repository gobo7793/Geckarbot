import discord
from discord.ext import commands
from conf import Config


def in_channel(channel_id):
    """
    Check if CMD can be used in the channel with given channel id.
    Can be used as command check function in decorators.
    """

    def predicate(ctx):
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        is_group = isinstance(ctx.channel, discord.GroupChannel)
        is_id = ctx.channel.id == channel_id
        return is_dm or is_group or is_id

    return commands.check(predicate)


def check_full_access(user: discord.Member):
    """
    Checks if the user has full access to bot commands. If you can, use
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES) instead.
    """
    for role in user.roles:
        if role.id in Config().FULL_ACCESS_ROLES:
            return True
    return False


def whitelist_check_id(user_id: int):
    """
    Checks if the given user can use the bot based on the debug whitelist.
    Note: The debug whitelist is active only if the list is not empty and debug mode is enabled.

    :param user_id: The user id to check
    :returns: If debug mode is disabled: True.
              If debug mode is enabled: False if user is not permitted to use the bot, otherwise True.
    """
    if (Config().DEBUG_MODE
            and len(Config().DEBUG_WHITELIST) > 0
            and user_id not in Config().DEBUG_WHITELIST):
        return False
    return True


def whitelist_check(user: discord.User):
    """
    Checks if the given user can use the bot based on the debug whitelist.
    Note: The debug whitelist is active only if debug mode is enabled.

    :param user: The user to check
    :returns: If debug mode is disabled: True.
              If debug mode is enabled: True only if User is on debug whitelist, else False.
    """
    return whitelist_check_id(user.id)
