#!/usr/bin/env python3
import datetime
import logging
import pkgutil
import sys
import traceback
from enum import Enum
from logging import handlers
from pathlib import Path
from typing import List

import discord
from discord.ext import commands

import injections
import subsystems
from base import BasePlugin, NotLoadable, ConfigurableType
from botutils import utils, permchecks, converters, stringutils
from conf import Config, Lang, Storage
from subsystems import timers, reactions, ignoring, dmlisteners, help, presence


class Exitcodes(Enum):
    """
    These exit codes are evaluated by the runscript and acted on accordingly.
    """
    SUCCESS = 0  # regular shutdown, doesn't come back up
    ERROR = 1  # some generic error
    HTTP = 2  # no connection to discord
    UPDATE = 10  # shutdown, update, restart
    RESTART = 11  # simple restart


class Geckarbot(commands.Bot):
    def __init__(self, *args, **kwargs):
        # self.geck_cogs = []
        self.guild = None
        self._plugins = []

        super().__init__(*args, **kwargs)

        Lang().bot = self
        Config().bot = self
        Storage().bot = self

        self.reaction_listener = reactions.ReactionListener(self)
        self.dm_listener = dmlisteners.DMListener(self)
        self.timers = timers.Mothership(self)
        self.ignoring = ignoring.Ignoring(self)
        self.helpsys = help.GeckiHelp(self)
        self.presence = presence.Presence(self)

    @property
    def plugins(self) -> List[BasePlugin]:
        """All plugins including normal and coreplugins"""
        return self._plugins

    def get_coreplugins(self) -> List[str]:
        """All coreplugins"""
        return [c.get_name()
                for c in self._plugins if c.get_configurable_type() == ConfigurableType.COREPLUGIN]

    def get_normalplugins(self) -> List[str]:
        """All normal plugins"""
        return [c.get_name()
                for c in self._plugins if c.get_configurable_type() == ConfigurableType.PLUGIN]

    def get_subsystem_list(self) -> List[str]:
        """All normal plugins"""
        subsys = []
        for modname in pkgutil.iter_modules(subsystems.__path__):
            subsys.append(modname.name)
        return subsys

    def configure(self, plugin):
        Config().load(plugin)
        Storage().load(plugin)
        Lang().remove_from_cache(plugin)

    def register(self, plugin_class, category=None, category_desc=None):
        """Registers the given plugin class or instance"""
        # Add Cog
        if isinstance(plugin_class, commands.Cog):
            plugin_object = plugin_class
        else:
            plugin_object = plugin_class(self)
        self.add_cog(plugin_object)

        self.plugins.append(plugin_object)

        # Load IO
        self.configure(plugin_object)

        # Set HelpCategory
        if isinstance(category, str) and category:
            if category_desc is None:
                category_desc = ""
            category = help.HelpCategory(category, description=category_desc)
        if category is None:
            cat = self.helpsys.register_category_by_name(plugin_object.get_name())
            cat.add_plugin(plugin_object)
        else:
            cat = self.helpsys.register_category(category)
            cat.add_plugin(plugin_object)

        logging.debug("Registered plugin {}".format(plugin_object.get_name()))

    def deregister(self, plugin: BasePlugin):
        """Deregisters the given plugin instance"""
        self.remove_cog(plugin.qualified_name)

        if plugin not in self.plugins:
            logging.debug("Tried deregistering plugin {}, but plugin is not registered".
                          format(plugin.get_name()))
            return

        self.helpsys.category_by_plugin(plugin).remove_plugin(plugin)
        self.plugins.remove(plugin)

        logging.debug("Deregistered plugin {}".format(plugin.get_name()))

    def plugin_objects(self, plugins_only=False):
        """
        Generator for all registered plugin objects without anything config-related
        """
        for el in self.plugins:
            if plugins_only and not isinstance(el, BasePlugin):
                continue
            yield el

    def load_plugins(self, plugin_dir):
        """
        Loads all plugins in plugin_dir.
        :return: Returns a list with the plugin names on which loading failed.
        """
        failed_list = []
        for el in pkgutil.iter_modules([plugin_dir]):
            if not self.load_plugin(plugin_dir, el[1]):
                failed_list.append(el[1])
        return failed_list

    def load_plugin(self, plugin_dir, plugin_name):
        """Loads the given plugin_name in plugin_dir, returns True if plugin loaded successfully"""
        try:
            to_import = "{}.{}".format(plugin_dir, plugin_name)
            try:
                pkgutil.importlib.import_module(to_import).Plugin(self)
            except AttributeError:
                to_import = "{}.{}.{}".format(plugin_dir, plugin_name, plugin_name)
                pkgutil.importlib.import_module(to_import).Plugin(self)
        except NotLoadable as e:
            logging.warning("Plugin {} could not be loaded: {}".format(plugin_name, e))
            plugin_instance = converters.get_plugin_by_name(self, plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False
        except Exception as e:
            logging.error("Unable to load plugin: {}:\n{}".format(plugin_name, traceback.format_exc()))
            plugin_instance = converters.get_plugin_by_name(self, plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False
        else:
            logging.info("Loaded plugin {}".format(plugin_name))
            return True

    def unload_plugin(self, plugin_name, save_config=True):
        """Unloads the plugin with the given plugin_name, returns True if plugin unloaded successfully"""
        try:
            plugin = converters.get_plugin_by_name(self, plugin_name)
            if plugin is None:
                return
            self.loop.create_task(plugin.shutdown())
            if save_config:
                Config.save(plugin)
                Storage.save(plugin)

            self.deregister(plugin)
        except Exception as e:
            logging.error("Unable to unload plugin: {}:\n{}".format(plugin_name, traceback.format_exc()))
            return False
        else:
            logging.info("Unloaded plugin {}".format(plugin_name))
            return True

    @staticmethod
    def set_debug_mode(mode):
        if mode == Config().DEBUG_MODE:
            return

        if mode:
            Config().DEBUG_MODE = True
        else:
            Config().DEBUG_MODE = False
        logging_setup()

    async def shutdown(self, status):
        try:
            status = status.value
        except AttributeError:
            pass
        self.timers.shutdown(status)
        logging.info("Shutting down.")
        logging.debug("Exit code: {}".format(status))
        sys.exit(status)


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
    Config().load_bot_config()
    injections.pre_injections()
    logging_setup()
    logging.getLogger(__name__).debug("Debug mode: on")
    bot = Geckarbot(command_prefix='!')
    injections.post_injections(bot)
    logging.info("Loading core plugins")
    failed_plugins = bot.load_plugins(Config().CORE_PLUGIN_DIR)

    @bot.event
    async def on_ready():
        """Loads plugins and prints on server that bot is ready"""
        guild = discord.utils.get(bot.guilds, id=Config().SERVER_ID)
        bot.guild = guild

        logging.info("Loading plugins")
        failed_plugins.extend(bot.load_plugins(Config().PLUGIN_DIR))

        if not Config().DEBUG_MODE:
            await bot.presence.start()

        logging.info(f"{bot.user} is connected to the following server: "
                     f"{guild.name} (id: {guild.id})")

        members = "\n - ".join([member.name for member in guild.members])
        logging.info(f"Server Members:\n - {members}")

        await utils.write_debug_channel(bot, f"Geckarbot {Config().VERSION} connected on "
                                             f"{guild.name} with {len(guild.members)} users.")
        await utils.write_debug_channel(bot, f"Loaded subsystems: {', '.join(bot.get_subsystem_list())}")
        await utils.write_debug_channel(bot, f"Loaded coreplugins: {', '.join(bot.get_coreplugins())}")
        await utils.write_debug_channel(bot, f"Loaded plugins: {', '.join(bot.get_normalplugins())}")
        await utils.write_debug_channel(bot, f"Failed loading plugins: {', '.join(failed_plugins)}")

    if not Config().DEBUG_MODE:
        @bot.event
        async def on_error(event, *args, **kwargs):
            """On bot errors print error state in debug channel"""
            exc_type, exc_value, exc_traceback = sys.exc_info()

            if (exc_type is commands.CommandNotFound
                    or exc_type is commands.DisabledCommand):
                return

            embed = discord.Embed(title=':x: Error', colour=0xe74c3c)  # Red
            embed.add_field(name='Error', value=exc_type)
            embed.add_field(name='Event', value=event)
            embed.timestamp = datetime.datetime.utcnow()

            ex_tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            is_tb_own_msg = len(ex_tb) > 2000
            if is_tb_own_msg:
                embed.description = "Exception Traceback see next message."
                ex_tb = stringutils.paginate(ex_tb.split("\n"), msg_prefix="```python\n", msg_suffix="```")
            else:
                embed.description = f"```python\n{ex_tb}```"

            await utils.write_debug_channel(bot, embed)
            if is_tb_own_msg:
                for msg in ex_tb:
                    await utils.write_debug_channel(bot, msg)

        @bot.event
        async def on_command_error(ctx, error):
            """Error handling for bot commands"""
            # No command or ignoring list handling
            if isinstance(error, (commands.CommandNotFound, commands.DisabledCommand)):
                return
            if isinstance(error, ignoring.UserBlockedCommand):
                await ctx.send("User {} has blocked the command.".format(converters.get_best_username(error.user)))

            # Check Failures
            elif isinstance(error, (commands.MissingRole, commands.MissingAnyRole)):
                await ctx.send("You don't have the correct role for this command.")
            elif isinstance(error, commands.NoPrivateMessage):
                await ctx.send("Command can't be executed in private messages.")
            elif isinstance(error, commands.CheckFailure):
                await ctx.send("Permission error.")

            # User input errors
            elif isinstance(error, commands.MissingRequiredArgument):
                await ctx.send("Required argument missing: {}".format(error.param))
            elif isinstance(error, commands.TooManyArguments):
                await ctx.send("Too many arguments given.")
            elif isinstance(error, commands.BadArgument):
                await ctx.send("Error on given argument: {}".format(error))
            elif isinstance(error, commands.UserInputError):
                await ctx.send("Wrong user input format: {}".format(error))

            # Other errors
            else:
                # error handling
                embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c)  # Red
                embed.add_field(name='Error', value=error)
                embed.add_field(name='Command', value=ctx.command)
                embed.add_field(name='Message', value=ctx.message.clean_content)
                if isinstance(ctx.channel, discord.TextChannel):
                    embed.add_field(name='Channel', value=ctx.channel.name)
                if isinstance(ctx.channel, discord.DMChannel):
                    embed.add_field(name='Channel', value=ctx.channel.recipient)
                if isinstance(ctx.channel, discord.GroupChannel):
                    embed.add_field(name='Channel', value=ctx.channel.recipients)
                embed.add_field(name='Author', value=ctx.author.display_name)
                embed.url = ctx.message.jump_url
                embed.timestamp = datetime.datetime.utcnow()

                ex_tb = "".join(traceback.TracebackException.from_exception(error).format())
                is_tb_own_msg = len(ex_tb) > 2000
                if is_tb_own_msg:
                    embed.description = "Exception Traceback see next message."
                    ex_tb = stringutils.paginate(ex_tb.split("\n"), msg_prefix="```python\n", msg_suffix="```")
                else:
                    embed.description = f"```python\n{ex_tb}```"

                await utils.write_debug_channel(bot, embed)
                if is_tb_own_msg:
                    for msg in ex_tb:
                        await utils.write_debug_channel(bot, msg)
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send("Unknown error while executing command.")

    @bot.event
    async def on_message(message):
        """Basic message and ignore list handling"""

        # DM handling
        if message.guild is None:
            if await bot.dm_listener.handle_dm(message):
                return

        # user on ignore list
        if bot.ignoring.check_user(message.author):
            return

        # debug mode whitelist
        if not permchecks.whitelist_check(message.author):
            return

        await bot.process_commands(message)

    @bot.check
    async def command_disabled(ctx):
        """
        Checks if a command is disabled or blocked for user.
        This check will be executed before other command checks.
        """
        if bot.ignoring.check_command(ctx):
            raise commands.DisabledCommand()
        if bot.ignoring.check_active_usage(ctx.author, ctx.command.qualified_name):
            raise commands.DisabledCommand()
        if bot.ignoring.check_passive_usage(ctx.author, ctx.command.qualified_name):
            raise commands.DisabledCommand()
        return True

    bot.run(Config().TOKEN)


if __name__ == "__main__":
    main()
