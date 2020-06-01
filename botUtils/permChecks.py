from discord.ext import commands


def in_channel(channel_id):
    """Check if CMD can be used in the channel with given channel id"""
    def predicate(ctx):
        return ctx.message.channel.id == channel_id
    return commands.check(predicate)

def exec_not_for_other_users(max_args_for_users, *roles):
    """Check the permissions to execute the command for others users only if mod.
    Returns True if cmd can be executed."""
    def predicate(ctx):
        if commands.has_any_role(roles):
            return True
        else:
            return len(ctx.args) <= max_args_for_users
    return commands.check(predicate)