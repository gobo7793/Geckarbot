import discord
from discord.ext import commands
from conf import Config


def in_channel(channel_id):
    """Check if CMD can be used in the channel with given channel id"""
    def predicate(ctx):
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        is_group = isinstance(ctx.channel, discord.GroupChannel)
        is_id = ctx.channel.id == channel_id
        return is_dm or is_group or is_id
    return commands.check(predicate)


def has_role_id(user: discord.Member, role_id):
    """
    Checks if user has the role with the id role_id.
    """
    for role in user.roles:
        if role.id == role_id:
            return True
    return False


def check_full_access(user: discord.Member):
    """
    Checks if the user has full access to bot commands. If you can, use
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES) instead.
    """
    for role in user.roles:
        if role.id in Config().FULL_ACCESS_ROLES:
            return True
    return False
