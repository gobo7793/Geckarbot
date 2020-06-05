from discord.ext.commands.bot import Bot
from conf import Config


async def write_debug_channel(bot: Bot, message):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(message)


async def write_debug_channel_embed(bot: Bot, embed):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(embed=embed)


def get_best_username(user):
    """
    :param user: User that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if user.nick is None:
        return user.name
    return user.nick


def clear_link(link):
    """Removes trailing and leading < and > from links"""
    if link.startswith('<'):
        link = link[1:]
    if link.endswith('>'):
        link = link[:-1]
    return link
