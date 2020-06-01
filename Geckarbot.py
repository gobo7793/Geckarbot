#!/usr/bin/env python3

import os
import traceback
import datetime
import discord

from pathlib import Path
from discord.ext import commands

from config import config
from botUtils.blacklist import Blacklist
from botUtils.greylist import Greylist
import botUtils

from botCommands.getting import gettingCommands
from botCommands.misc import miscCommands
from botCommands.mod import modCommands

bot = commands.Bot(command_prefix='!')
config.read_config_file()
blacklist = Blacklist(bot)
greylist = Greylist(bot)

@bot.event
async def on_ready():
    """Print basic info that bot is ready"""
    guild = discord.utils.get(bot.guilds, id=config.SERVER_ID)
    print(f"{bot.user} is connected to the following server:\n"
        f"{guild.name}(id: {guild.id})")

    members = "\n - ".join([member.name for member in guild.members])
    print(f"Server Members:\n - {members}")

    await botUtils.write_debug_channel(bot, f"Geckarbot v{config.VERSION} connected on "
                                            f"{guild.name} with {len(guild.members)} users.")

if not config.DEBUG_MODE:
    @bot.event
    async def on_error(event, *args, **kwargs):
        """On bot errors print error state in debug channel"""
        embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c) # Red
        embed.add_field(name='Event', value=event)
        embed.description = '```py\n%s\n```' % traceback.format_exc()
        embed.timestamp = datetime.datetime.utcnow()
        debug_chan = bot.get_channel(config.DEBUG_CHAN_ID)
        if debug_chan is not None:
            await debug_chan.send(embed=embed)

    @bot.event
    async def on_command_error(ctx, error):
        """Error handling for bot commands"""
        if isinstance(error, commands.errors.CommandNotFound):
            return

        # Check Failures
        elif isinstance(error, commands.errors.MissingRole) or isinstance(error, commands.errors.MissingAnyRole):
            await ctx.send("You don't have the correct role for this command.")
        elif isinstance(error, commands.errors.NoPrivateMessage):
            await ctx.send("Command can't be executed in private messages.")
        elif isinstance(error, commands.errors.CheckFailure):
            return

        # User input errors
        elif isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send("Required argument missing.")
        elif isinstance(error, commands.errors.TooManyArguments):
            await ctx.send("Too many arguments given.")
        elif isinstance(error, commands.errors.UserInputError):
            await ctx.send("Wrong user input format.")
        else:
            # error handling
            embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c) # Red
            embed.add_field(name='Error', value=error)
            embed.add_field(name='Arguments', value=ctx.args)
            embed.add_field(name='Command', value=ctx.command)
            embed.add_field(name='Message', value=ctx.message)
            embed.description = '```py\n%s\n```' % traceback.format_exc()
            embed.timestamp = datetime.datetime.utcnow()
            debug_chan = bot.get_channel(config.DEBUG_CHAN_ID)
            if(debug_chan != None):
                await debug_chan.send(embed=embed)
            await ctx.send("Error while executing command.")


@bot.event
async def on_member_join(member):
    """Write new users a short dm"""
    await member.create_dm()
    await member.dm_channel.send(f"Hi {member.display_name}, Willkommen auf dem #storm-Discord-Server!\n"
                                 f"Schreibe am besten einem @mod, um die entsprechenden Rechte zu bekommen.")


@bot.event
async def on_message(message):
    """Basic message and blacklisting handling"""
    if blacklist.is_member_on_blacklist(message.author):
        return
    await bot.process_commands(message)

# Adding command cogs
bot.add_cog(gettingCommands(bot))
bot.add_cog(miscCommands(bot))
bot.add_cog(modCommands(bot, blacklist, greylist))

bot.run(config.TOKEN)
