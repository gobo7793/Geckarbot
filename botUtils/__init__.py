import os
from discord.ext import commands
from discord.ext.commands.bot import Bot
from config import config

async def write_debug_channel(bot:Bot, message):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(config.DEBUG_CHAN_ID)
    if(debug_chan != None):
        await debug_chan.send(message)

def in_channel(channel_id):
    def predicate(ctx):
        return ctx.message.channel.id == channel_id
    return commands.check(predicate)