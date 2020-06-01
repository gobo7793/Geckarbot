import os
from discord.ext import commands
from discord.ext.commands.bot import Bot
from config import config


async def write_debug_channel(bot: Bot, message):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(config.DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(message)

async def write_debug_channel_embed(bot: Bot, embed):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(config.DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(embed=embed)

def clear_link(link):
    """Removes trailing and leading < and > from links"""
    if link.startswith('<'):
        link = link[1:]
    if link.endswith('>'):
        link = link[:-1]
    return link
