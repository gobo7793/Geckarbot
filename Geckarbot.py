#!/usr/bin/env python3
import logging
import pkgutil
import sys
import traceback
import inspect
import datetime
import pprint
from enum import Enum
from logging import handlers
from pathlib import Path
from typing import List

import discord
from discord.ext import commands

import injections
import subsystems
from base import BasePlugin, NotLoadable, ConfigurableType, PluginNotFound
from botutils import utils, permchecks, converters, stringutils
from conf import Config, Lang, Storage, ConfigurableData
from subsystems import timers, reactions, ignoring, dmlisteners, help, presence, liveticker


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
    """
    Basic bot info
    """
    NAME = "Geckarbot"
    VERSION = "2.6.4"
    PLUGIN_DIR = "plugins"
    CORE_PLUGIN_DIR = "coreplugins"
    CONFIG_DIR = "config"
    STORAGE_DIR = "storage"
    LANG_DIR = "lang"
    DEFAULT_LANG = "en"
    RESOURCE_DIR = "resource"

    """
    Config
    """
    TOKEN = None
    SERVER_ID = None
    CHAN_IDS = None
    ROLE_IDS = None
    DEBUG_MODE = None
    DEBUG_USERS = None
    GOOGLE_API_KEY = None
    LANGUAGE_CODE = None

    ADMIN_CHAN_ID = None
    DEBUG_CHAN_ID = None
    MOD_CHAN_ID = None
    SERVER_ADMIN_ROLE_ID = None
    BOT_ADMIN_ROLE_ID = None
    MOD_ROLE_ID = None
    ADMIN_ROLES = None
    MOD_ROLES = None

    def __init__(self, *args, **kwargs):
        logging.info("Starting {} {}".format(self.NAME, self.VERSION))
        self.guild = None
        self._plugins = []

        super().__init__(*args, **kwargs)

        Lang().bot = self
        Config().bot = self
        Storage().bot = self
        self.load_config()

        self.reaction_listener = reactions.ReactionListener(self)
        self.dm_listener = dmlisteners.DMListener(self)
        self.timers = timers.Mothership(self)
        self.ignoring = ignoring.Ignoring(self)
        self.helpsys = help.GeckiHelp(self)
        self.presence = presence.Presence(self)
        self.liveticker = liveticker.Liveticker(self)

    def load_config(self):
        """
        Loads the bot config file and sets all config variables.
        """
        dummy = ConfigurableData(Config, self)
        cfg = dummy.get()
        self.set_debug_mode(cfg.get('DEBUG_MODE', False))
        self.TOKEN = cfg.get('DISCORD_TOKEN', 0)
        self.SERVER_ID = cfg.get('SERVER_ID', 0)
        self.CHAN_IDS = cfg.get('CHAN_IDS', {})
        self.ROLE_IDS = cfg.get('ROLE_IDS', {})
        self.DEBUG_USERS = cfg.get('DEBUG_USERS', cfg.get('DEBUG_WHITELIST', []))
        self.GOOGLE_API_KEY = cfg.get('GOOGLE_API_KEY', "")
        self.LANGUAGE_CODE = cfg.get('LANG', self.DEFAULT_LANG)

        self.ADMIN_CHAN_ID = self.CHAN_IDS.get('admin', 0)
        self.DEBUG_CHAN_ID = self.CHAN_IDS.get('debug', self.CHAN_IDS.get('bot-interna', 0))
        self.MOD_CHAN_ID = self.CHAN_IDS.get('mod', 0)
        self.SERVER_ADMIN_ROLE_ID = self.ROLE_IDS.get('server_admin', self.ROLE_IDS.get('admin', 0))
        self.BOT_ADMIN_ROLE_ID = self.ROLE_IDS.get('bot_admin', self.ROLE_IDS.get('botmaster', 0))
        self.MOD_ROLE_ID = self.ROLE_IDS.get('mod', 0)
        self.ADMIN_ROLES = [self.BOT_ADMIN_ROLE_ID, self.SERVER_ADMIN_ROLE_ID]
        self.MOD_ROLES = [self.BOT_ADMIN_ROLE_ID, self.SERVER_ADMIN_ROLE_ID, self.MOD_ROLE_ID]

    def get_default(self, container=None):
        raise RuntimeError("Config file missing")

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

    def get_available_plugins(self) -> List[str]:
        """Get all available normal plugins including loaded plugins"""
        avail = []
        for modname in pkgutil.iter_modules([self.PLUGIN_DIR]):
            avail.append(modname.name)
        return avail

    def get_subsystem_list(self) -> List[str]:
        """All normal plugins"""
        subsys = []
        for modname in pkgutil.iter_modules(subsystems.__path__):
            subsys.append(modname.name)
        return subsys

    def get_name(self):
        return self.NAME.lower()

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
            category = help.HelpCategory(self, category, description=category_desc)
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

    def import_plugin(self, module_name):
        module = pkgutil.importlib.import_module(module_name)
        members = inspect.getmembers(module)
        found = False
        for name, obj in members:
            if name == "Plugin":
                found = True
                obj(self)
        if not found:
            raise PluginNotFound(members)

    def load_plugin(self, plugin_dir, plugin_name):
        """Loads the given plugin_name in plugin_dir, returns True if plugin loaded successfully"""
        try:
            to_import = "{}.{}".format(plugin_dir, plugin_name)
            try:
                self.import_plugin(to_import)
            except PluginNotFound:
                to_import = "{}.{}.{}".format(plugin_dir, plugin_name, plugin_name)
                self.import_plugin(to_import)
        except NotLoadable as e:
            logging.warning("Plugin {} could not be loaded: {}".format(plugin_name, e))
            plugin_instance = converters.get_plugin_by_name(plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False
        except PluginNotFound as e:
            logging.error("Unable to load plugin '{}': Plugin class not found".format(plugin_name))
            logging.debug("Members: {}".format(pprint.pformat(e.members)))
        except Exception as e:
            logging.error("Unable to load plugin '{}':\n{}".format(plugin_name, traceback.format_exc()))
            plugin_instance = converters.get_plugin_by_name(plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False
        else:
            logging.info("Loaded plugin {}".format(plugin_name))
            return True

    def unload_plugin(self, plugin_name, save_config=True):
        """Unloads the plugin with the given plugin_name, returns True if plugin unloaded successfully"""
        try:
            plugin = converters.get_plugin_by_name(plugin_name)
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

    def set_debug_mode(self, mode):
        if mode == self.DEBUG_MODE:
            return

        if mode:
            self.DEBUG_MODE = True
        else:
            self.DEBUG_MODE = False
        logging_setup(debug=mode)

    async def shutdown(self, status):
        try:
            status = status.value
        except AttributeError:
            pass
        self.timers.shutdown(status)
        logging.info("Shutting down.")
        logging.debug("Exit code: {}".format(status))
        sys.exit(status)


def intent_setup():
    intents = discord.Intents.default()
    intents.members = True
    return intents


def logging_setup(debug=False):
    """
    Put all debug loggers on info and everything else on info/debug, depending on config
    """
    level = logging.INFO
    if debug:
        level = logging.DEBUG

    Path("logs/").mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.TimedRotatingFileHandler(filename="logs/geckarbot.log",
                                                             when="midnight", interval=1, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
    logger = logging.getLogger('')
    logger.setLevel(level)
    logger.handlers = [file_handler, console_handler]

    for el in logging.root.manager.loggerDict:
        logger = logging.root.manager.loggerDict[el]
        if isinstance(logger, logging.PlaceHolder):
            continue
        logger.setLevel(logging.INFO)


def main():
    injections.pre_injections()
    logging_setup()
    logging.getLogger(__name__).debug("Debug mode: on")
    intents = intent_setup()
    bot = Geckarbot(command_prefix='!', intents=intents)
    injections.post_injections(bot)
    logging.info("Loading core plugins")
    failed_plugins = bot.load_plugins(bot.CORE_PLUGIN_DIR)

    @bot.event
    async def on_ready():
        """Loads plugins and prints on server that bot is ready"""
        guild = discord.utils.get(bot.guilds, id=bot.SERVER_ID)
        bot.guild = guild

        logging.info("Loading plugins")
        failed_plugins.extend(bot.load_plugins(bot.PLUGIN_DIR))

        if not bot.DEBUG_MODE:
            await bot.presence.start()

        logging.info(f"{bot.user} is connected to the following server: "
                     f"{guild.name} (id: {guild.id})")

        members = "\n - ".join([member.name for member in guild.members])
        logging.info(f"Server Members:\n - {members}")

        await utils.write_debug_channel(f"Geckarbot {bot.VERSION} connected on "
                                             f"{guild.name} with {len(guild.members)} users.")
        await utils.write_debug_channel(f"Loaded subsystems: {', '.join(bot.get_subsystem_list())}")
        await utils.write_debug_channel(f"Loaded coreplugins: {', '.join(bot.get_coreplugins())}")
        await utils.write_debug_channel(f"Loaded plugins: {', '.join(bot.get_normalplugins())}")
        if len(failed_plugins) < 1:
            failed_plugins.append("None, all plugins loaded successfully!")
        await utils.write_debug_channel(f"Failed loading plugins: {', '.join(failed_plugins)}")

    if not bot.DEBUG_MODE:
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

            await utils.write_debug_channel(embed)
            if is_tb_own_msg:
                for msg in ex_tb:
                    await utils.write_debug_channel(msg)

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

                await utils.write_debug_channel(embed)
                if is_tb_own_msg:
                    for msg in ex_tb:
                        await utils.write_debug_channel(msg)
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                msg = "Unknown error while executing command."
                if hasattr(error, "user_message"):
                    msg = error.user_message
                await ctx.send(msg)

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
        if not permchecks.debug_user_check(message.author):
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

    bot.run(bot.TOKEN)


if __name__ == "__main__":
    main()
