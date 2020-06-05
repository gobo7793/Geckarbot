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


def check_full_access(user: discord.Member):
    """Checks if the user has full access to bot commands"""
    for role in user.roles:
        if role.id in [Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID]:
            return True
    return False
