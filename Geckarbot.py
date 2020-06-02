#!/usr/bin/env python3

import traceback
import datetime
import discord
import pkgutil
import logging

from discord.ext import commands

from conf import Config
from botUtils.blacklist import Blacklist
from botUtils.greylist import Greylist
from botUtils import utils

#PLUGINDIR = "botCommands"


class Geckarbot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blacklist = Blacklist(self)
        self.greylist = Greylist(self)

bot = Geckarbot(command_prefix='!')
Config().read_config_file()


@bot.event
async def on_ready():
    """Print basic info that bot is ready"""
    guild = discord.utils.get(bot.guilds, id=Config().SERVER_ID)
    logging.info(f"{bot.user} is connected to the following server:\n"
                 f"{guild.name}(id: {guild.id})")

    members = "\n - ".join([member.name for member in guild.members])
    logging.info(f"Server Members:\n - {members}")

    await utils.write_debug_channel(bot, f"Geckarbot v{Config().VERSION} connected on "
                                            f"{guild.name} with {len(guild.members)} users.")

if not Config().DEBUG_MODE:
    @bot.event
    async def on_error(event, *args, **kwargs):
        """On bot errors print error state in debug channel"""
        embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c)  # Red
        embed.add_field(name='Event', value=event)
        embed.description = '```py\n%s\n```' % traceback.format_exc()
        embed.timestamp = datetime.datetime.utcnow()
        debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
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
            embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c)  # Red
            embed.add_field(name='Error', value=error)
            embed.add_field(name='Arguments', value=ctx.args)
            embed.add_field(name='Command', value=ctx.command)
            embed.add_field(name='Message', value=ctx.message)
            embed.description = '```py\n%s\n```' % traceback.format_exc()
            embed.timestamp = datetime.datetime.utcnow()
            debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
            if debug_chan is not None:
                await debug_chan.send(embed=embed)
            await ctx.send("Error while executing command.")


#@bot.event
#async def on_member_join(member):
#    """Write new users a short dm"""
#    await member.create_dm()
#    await member.dm_channel.send(f"Hi {member.display_name}, Willkommen auf dem Communityserver!\n"
#                                 f"Schreibe am besten einem @mod, um die entsprechenden Rechte zu bekommen.")


@bot.event
async def on_message(message):
    """Basic message and blacklisting handling"""
    if bot.blacklist.is_member_on_blacklist(message.author):
        return
    if Config().DEBUG_USER_ID_REACTING != 0:
        if message.author.id == Config().DEBUG_USER_ID_REACTING:
            await bot.process_commands(message)
        else:
            return
    else:
        await bot.process_commands(message)


def load_plugins():
    r = []

    # import
    for el in pkgutil.iter_modules([Config().PLUGINDIR]):
        plugin = el[1]
        try:
            p = pkgutil.importlib.import_module("{}.{}".format(Config().PLUGINDIR, plugin))
            p.register(bot)
        except Exception as e:
            logging.error("Unable to load plugin: {} ({})".format(plugin, e))
            continue
        else:
            r.append(p)
            logging.info("Loaded plugin {}".format(plugin))

    return r


def main():
    logging.basicConfig(level=logging.INFO)
    load_plugins()

    bot.run(Config().TOKEN)

if __name__ == "__main__":
    main()
