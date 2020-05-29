import os
from dotenv import load_dotenv
from discord.ext.commands.bot import Bot

load_dotenv()
DEBUG_CHAN_ID = int(os.getenv("DEBUG_CHAN_ID"))

async def write_debug_channel(bot:Bot, message):
    debug_chan = bot.get_channel(DEBUG_CHAN_ID)
    if(debug_chan != None):
        await debug_chan.send(message)
