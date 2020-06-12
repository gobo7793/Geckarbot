#!/usr/bin/env python3

import traceback
import datetime
import discord
import pkgutil
import logging
import sys
from enum import Enum
from logging import handlers
from pathlib import Path

from discord.ext import commands

from conf import Config, PluginSlot
from botutils import utils


class Exitcodes(Enum):
    """
    These exit codes are evaluated by the runscript and acted on accordingly.
    """
    SUCCESS = 0  # regular shutdown, doesn't come back up
    ERROR = 1  # some generic error
    HTTP = 2  # no connection to discord
    RESTART = 10  # simple restart
    UPDATE = 11  # shutdown, update, restart


class BasePlugin(commands.Cog):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def shutdown(self):
        """
        Is called when the bot is shutting down. If you have cleanup to do, do it here.
        Needs to be a coroutine (async).
        """
        pass

    def default_config(self):
        """Returns an empty default config"""
        return {}


class Geckarbot(commands.Bot):
    def __init__(self, *args, **kwargs):
        self.coredata = {}
        self.geck_cogs = []
        self.guild = None
        self.plugins = None
        super().__init__(*args, **kwargs)

    def register(self, plugin_class):
        print(isinstance(plugin_class, BasePlugin))  # todo figure out why this is False
        if isinstance(plugin_class, commands.Cog):
            plugin_object = plugin_class
        else:
            plugin_object = plugin_class(self)
        self.add_cog(plugin_object)
        self.geck_cogs.append(plugin_object)

        plugin_slot = PluginSlot(plugin_object)
        Config().plugins.append(plugin_slot)
        Config().load(plugin_object)

    def plugin_objects(self):
        """
        Generator for all registered plugin objects without anything config-related
        """
        for el in Config().plugins:
            yield el.instance

    def plugin_name(self, plugin):
        """
        Returns a human-readable name for Plugin plugin.
        """
        return plugin.__module__.rsplit(".", 1)[1] # same as for PluginSlot.name

    def load_plugins(self, plugin_dir):
        r = []

        # import
        for el in pkgutil.iter_modules([plugin_dir]):
            plugin = el[1]
            try:
                p = pkgutil.importlib.import_module("{}.{}".format(plugin_dir, plugin))
                p = p.Plugin(self)
            except Exception as e:
                logging.error("Unable to load plugin: {}:\n{}".format(plugin, traceback.format_exc()))
                continue
            else:
                r.append(p)
                logging.info("Loaded plugin {}".format(plugin))

        return r

    async def shutdown(self, status):
        sys.exit(status.value())


def logging_setup():
    """
    Put all debug loggers on info and everything else on info/debug, depending on config
    """
    level = logging.INFO
    if Config().DEBUG_MODE:
        level = logging.DEBUG

    Path("logs/").mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.TimedRotatingFileHandler(filename="logs/geckarbot.log", when="midnight", interval=1)
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
    logger = logging.getLogger('')
    logger.setLevel(level)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    for el in logging.root.manager.loggerDict:
        logger = logging.root.manager.loggerDict[el]
        if isinstance(logger, logging.PlaceHolder):
            continue
        logger.setLevel(logging.INFO)


def main():
    Config().load_bot()
    logging_setup()
    logging.getLogger(__name__).debug("Debug mode: on")
    bot = Geckarbot(command_prefix='!')
    logging.info("Loading core plugins")
    bot.plugins = bot.load_plugins(Config().CORE_PLUGIN_DIR)

    @bot.event
    async def on_ready():
        """Loads plugins and prints on server that bot is ready"""
        guild = discord.utils.get(bot.guilds, id=Config().SERVER_ID)
        bot.guild = guild

        logging.info("Loading plugins")
        bot.plugins.extend(bot.load_plugins(Config().PLUGIN_DIR))

        logging.info(f"{bot.user} is connected to the following server:\n"
                     f"{guild.name}(id: {guild.id})")

        members = "\n - ".join([member.name for member in guild.members])
        logging.info(f"Server Members:\n - {members}")

        await utils.write_debug_channel(bot, f"Geckarbot {Config().VERSION} connected on "
                                             f"{guild.name} with {len(guild.members)} users.")

    if not Config().DEBUG_MODE:
        @bot.event
        async def on_error(event, *args, **kwargs):
            """On bot errors print error state in debug channel"""
            embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c)  # Red
            embed.add_field(name='Event', value=event)
            embed.description = '```python\n{}\n```'.format(traceback.format_exc())
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
                embed.description = '```python\n{}\n```'.format(traceback.format_exc())
                embed.timestamp = datetime.datetime.utcnow()
                debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
                if debug_chan is not None:
                    await debug_chan.send(embed=embed)
                await ctx.send("Error while executing command.")

    @bot.event
    async def on_message(message):
        """Basic message and blacklisting handling"""
        
        if ('blacklist' in bot.coredata
            and bot.coredata['blacklist'].is_member_on_blacklist(message.author)):
            return

        ctx = await bot.get_context(message)
        if (ctx.valid
            and 'disabled_cmds' in bot.coredata
            and not bot.coredata['disabled_cmds'].can_cmd_executed(ctx.command.name, ctx.channel)):
            return

        if Config().DEBUG_MODE and len(Config().DEBUG_WHITELIST) > 0:
            if message.author.id in Config().DEBUG_WHITELIST:
                await bot.process_commands(message)
            else:
                return
        else:
            await bot.process_commands(message)

    bot.run(Config().TOKEN)

if __name__ == "__main__":
    main()
