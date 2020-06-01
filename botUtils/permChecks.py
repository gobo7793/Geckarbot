import discord
from discord.ext import commands


def in_channel(channel_id):
    """Check if CMD can be used in the channel with given channel id"""
    def predicate(ctx):
        return (isinstance(ctx.channel, discord.DMChannel)
                    or isinstance(ctx.channel, discord.GroupChannel)
                    or ctx.channel.id is channel_id)
    return commands.check(predicate)

def check_full_access(user:discord.Member):
    """Checks if the user has full access to bot commands"""
    for role in user.roles:
        if role.name in ["mod", "botmaster"]:
            return True
    return False
