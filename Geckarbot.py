import os
import traceback
import datetime
import discord

from dotenv import load_dotenv
from discord.ext import commands

from sportCommands import sportCommands
from funCommands import funCommands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME")
DEBUG_CHAN_ID = os.getenv("DEBUG_CHAN_ID")

bot = commands.Bot(command_prefix='!')

@bot.event
async def on_ready():
    guild = discord.utils.get(bot.guilds, name=SERVER_NAME)
    print(f"{bot.user} is connected to the following server:\n"
        f"{guild.name}(id: {guild.id})")

    members = "\n - ".join([member.name for member in guild.members])
    print(f"Server Members:\n - {members}")
    
@bot.event
async def on_error(event, *args, **kwargs):
    embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c) #Red
    embed.add_field(name='Event', value=event)
    embed.description = '```py\n%s\n```' % traceback.format_exc()
    embed.timestamp = datetime.datetime.utcnow()
    debug_chan = bot.get_channel(int(DEBUG_CHAN_ID))
    if(debug_chan != None):
        await debug_chan.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c) #Red
    embed.add_field(name='Error', value=error)
    embed.add_field(name='Arguments', value=ctx.args)
    embed.add_field(name='Command', value=ctx.command)
    embed.add_field(name='Message', value=ctx.message)
    embed.description = '```py\n%s\n```' % traceback.format_exc()
    embed.timestamp = datetime.datetime.utcnow()
    debug_chan = bot.get_channel(int(DEBUG_CHAN_ID))
    if(debug_chan != None):
        await debug_chan.send(embed=embed)

# Adding commands
bot.add_cog(sportCommands())
bot.add_cog(funCommands())

bot.run(TOKEN)
