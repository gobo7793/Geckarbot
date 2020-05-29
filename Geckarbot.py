import os
import traceback
import datetime
import discord

from pathlib import Path
from dotenv import load_dotenv
from discord.ext import commands

from utils.blacklist import blacklist
import utils

from botCommands.sport import sportCommands
from botCommands.fun import funCommands
from botCommands.mod import modCommands
from botCommands.dsc import dscCommands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME")
DEBUG_CHAN_ID = int(os.getenv("DEBUG_CHAN_ID"))
DEBUG_MODE = os.getenv("DEBUG_MODE", False)

bot = commands.Bot(command_prefix='!')
blacklist = blacklist(bot)

@bot.event
async def on_ready():
    guild = discord.utils.get(bot.guilds, name=SERVER_NAME)
    print(f"{bot.user} is connected to the following server:\n"
        f"{guild.name}(id: {guild.id})")

    members = "\n - ".join([member.name for member in guild.members])
    print(f"Server Members:\n - {members}")

    await utils.write_debug_channel(bot, f"Bot connected on {guild.name} with {len(guild.members)} users.")
    
@bot.event
async def on_error(event, *args, **kwargs):
    embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c) #Red
    embed.add_field(name='Event', value=event)
    embed.description = '```py\n%s\n```' % traceback.format_exc()
    embed.timestamp = datetime.datetime.utcnow()
    debug_chan = bot.get_channel(DEBUG_CHAN_ID)
    if(debug_chan != None):
        await debug_chan.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.MissingRole) or isinstance(error, commands.errors.MissingAnyRole):
        await ctx.send("You don't have the correct role for this command.")
    elif isinstance(error, commands.errors.NoPrivateMessage):
        await ctx.send("Command can't be executed in private messages.")
    elif isinstance(error, commands.errors.CheckFailure):
        await ctx.send("Error while checking user rights to execute command.")
    elif isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send("Required argument missing.")
    elif isinstance(error, commands.errors.TooManyArguments):
        await ctx.send("Too many arguments given.")
    elif isinstance(error, commands.errors.UserInputError):
        await ctx.send("Wrong user input format.")
    else:
        # error handling
        embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c) #Red
        embed.add_field(name='Error', value=error)
        embed.add_field(name='Arguments', value=ctx.args)
        embed.add_field(name='Command', value=ctx.command)
        embed.add_field(name='Message', value=ctx.message)
        embed.description = '```py\n%s\n```' % traceback.format_exc()
        embed.timestamp = datetime.datetime.utcnow()
        debug_chan = bot.get_channel(DEBUG_CHAN_ID)
        if(debug_chan != None):
            await debug_chan.send(embed=embed)
        await ctx.send("Error while executing command.")

@bot.event
async def on_member_join(member):
    await member.create_dm()
    await member.dm_channel.send(f"Hi {member.name}, Willkommen auf dem #storm-Discord-Server!\n"
                   "Schreibe am besten einem @mod, um die entsprechenden Rechte zu bekommen.")

@bot.event
async def on_message(message):
    if blacklist.isUserOnBlacklist(message.author):
        #await write_debug_channel(f"User {message.author.name} tried to use {message.content}.")
        return
    await bot.process_commands(message)

# Adding commands
bot.add_cog(sportCommands(bot))
bot.add_cog(funCommands(bot))
bot.add_cog(modCommands(bot, blacklist))
bot.add_cog(dscCommands(bot))

bot.run(TOKEN)
