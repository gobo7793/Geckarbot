#!/usr/bin/env python3
# pylint: disable=invalid-name,broad-except,unused-import

import datetime
import inspect
import locale
import logging
import pkgutil
import pprint
import sys
import traceback
from enum import Enum
from logging import handlers
from pathlib import Path
from typing import List, Union

import discord
from discord.ext import commands

import injections
import subsystems
from base import BasePlugin, NotLoadable, ConfigurableType, PluginClassNotFound
from botutils import utils, permchecks, converters, stringutils
from data import Config, Lang, Storage, ConfigurableData
from subsystems import timers, reactions, ignoring, dmlisteners, helpsys, presence, liveticker


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
    VERSION = "2.10.0"
    PLUGIN_DIR = "plugins"
    CORE_PLUGIN_DIR = "coreplugins"
    CONFIG_DIR = "config"
    STORAGE_DIR = "storage"
    LANG_DIR = "lang"
    DEFAULT_LANG = "en_US"
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
    PLUGINS = None

    ADMIN_CHAN_ID = None
    DEBUG_CHAN_ID = None
    MOD_CHAN_ID = None
    SERVER_ADMIN_ROLE_ID = None
    BOT_ADMIN_ROLE_ID = None
    MOD_ROLE_ID = None
    ADMIN_ROLES = None
    MOD_ROLES = None
    LOAD_PLUGINS = None
    NOT_LOAD_PLUGINS = None

    def __init__(self, *args, **kwargs):
        logging.info("Starting %s %s", self.NAME, self.VERSION)
        self.guild = None
        self._plugins = []

        super().__init__(*args, **kwargs)

        Lang().bot = self
        Config().bot = self
        Storage().bot = self
        self.load_config()
        self._set_locale()

        self.add_check(self.command_disabled)

        self.reaction_listener = reactions.ReactionListener(self)
        self.dm_listener = dmlisteners.DMListener(self)
        self.timers = timers.Mothership(self)
        self.ignoring = ignoring.Ignoring(self)
        self.helpsys = helpsys.GeckiHelp(self)
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
        self.PLUGINS = cfg.get('PLUGINS', {})

        self.ADMIN_CHAN_ID = self.CHAN_IDS.get('admin', 0)
        self.DEBUG_CHAN_ID = self.CHAN_IDS.get('debug', self.CHAN_IDS.get('bot-interna', 0))
        self.MOD_CHAN_ID = self.CHAN_IDS.get('mod', 0)
        self.SERVER_ADMIN_ROLE_ID = self.ROLE_IDS.get('server_admin', self.ROLE_IDS.get('admin', 0))
        self.BOT_ADMIN_ROLE_ID = self.ROLE_IDS.get('bot_admin', self.ROLE_IDS.get('botmaster', 0))
        self.MOD_ROLE_ID = self.ROLE_IDS.get('mod', 0)
        self.ADMIN_ROLES = [self.BOT_ADMIN_ROLE_ID, self.SERVER_ADMIN_ROLE_ID]
        self.MOD_ROLES = [self.BOT_ADMIN_ROLE_ID, self.SERVER_ADMIN_ROLE_ID, self.MOD_ROLE_ID]
        self.LOAD_PLUGINS = self.PLUGINS.get('load', [])
        self.NOT_LOAD_PLUGINS = self.PLUGINS.get('not_load', [])

    def default_config(self, container=None):
        # pylint: disable=no-self-use
        # config/geckarbot.json must be provided or the bot can't start
        raise RuntimeError("Config file missing")

    def _set_locale(self):
        """
        Sets the localization settings to the LANGUAGE_CODE configuration
        """
        locale.setlocale(locale.LC_ALL, self.LANGUAGE_CODE + ".utf-8")
        logging.info("Localization set to '%s'", locale.getlocale(locale.LC_ALL))

    @property
    def plugins(self) -> List[BasePlugin]:
        """All plugins including normal and coreplugins"""
        return self._plugins

    def get_coreplugins(self) -> List[str]:
        """All coreplugins"""
        return [c.get_name() for c in self._plugins
                if c.get_configurable_type() == ConfigurableType.COREPLUGIN]

    def get_normalplugins(self) -> List[str]:
        """All normal plugins"""
        return [c.get_name() for c in self._plugins
                if c.get_configurable_type() == ConfigurableType.PLUGIN]

    def get_all_available_plugins(self) -> List[str]:
        """Get all available normal plugins including loaded plugins"""
        avail = []
        for modname in pkgutil.iter_modules([self.PLUGIN_DIR]):
            avail.append(modname.name)
        return avail

    def get_unloaded_plugins(self) -> List[str]:
        """Get all available normal plugins including loaded plugins"""
        return [x for x in self.get_all_available_plugins()
                if x not in self.get_normalplugins()]

    @staticmethod
    def get_subsystem_list() -> List[str]:
        """All normal plugins"""
        subsys = []
        for modname in pkgutil.iter_modules(subsystems.__path__):
            subsys.append(modname.name)
        return subsys

    def get_name(self):
        return self.NAME.lower()

    @staticmethod
    def configure(plugin):
        """
        Loads Config, Storage and Lang data for given plugin

        :param plugin: The plugin to load
        """
        Config().load(plugin)
        Storage().load(plugin)
        Lang().remove_from_cache(plugin)

    def register(self, plugin_class,
                 category: Union[str, helpsys.DefaultCategories, helpsys.HelpCategory, None] = None,
                 category_desc: str = None):
        """
        Registers a plugin

        :param plugin_class: The plugin instance inherited by `base.BasePlugin` to be registered
        :param category: The help category for the commands of the plugins.
            If none, the Help Subsystem creates one based on the plugin name.
        :param category_desc: The description of the help category.
        :returns: `True` if plugin is registered successfully or `False` if Plugin is no valid plugin class
        """
        if not isinstance(plugin_class, BasePlugin):
            logging.debug("Attempt plugin register for plugin object %s, but it doesn't inherit from BasePlugin!",
                          plugin_class)
            return False

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
        if category_desc is None:
            category_desc = ""
        if isinstance(category, str) and category:
            category = helpsys.HelpCategory(self, category, desc=category_desc)
        if category is None:
            cat = self.helpsys.register_category_by_name(plugin_object.get_name(), description=category_desc)
            cat.add_plugin(plugin_object)
        else:
            cat = self.helpsys.register_category(category)
            cat.add_plugin(plugin_object)

        logging.debug("Registered plugin %s", plugin_object.get_name())
        return True

    def deregister(self, plugin: BasePlugin):
        """
        Deregisters a plugin

        :param plugin: The plugin instance to deregister
        :returns: `True` if plugin successfully deregistered or `False` if plugin is not registered.
        """
        self.remove_cog(plugin.qualified_name)

        if plugin not in self.plugins:
            logging.debug("Tried deregistering plugin %s, but plugin is not registered", plugin.get_name())
            return False

        self.helpsys.purge_plugin(plugin)
        self.plugins.remove(plugin)

        logging.debug("Deregistered plugin %s", plugin.get_name())
        return True

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
        Loads all plugins in given plugin_dir with following conditions:
            1. If LOAD_PLUGINS is empty: All available plugins will be loaded
            2. If LOAD_PLUGINS is not empty: Only the plugins in this list will be loaded
            3. From the plugins that should be loaded, the plugins listed in NOT_LOAD_PLUGINS won't be loaded

        Plugins are indicated by their names. These conditions don't apply to core plugins in CORE_PLUGIN_DIR.

        :return: Returns a list with the plugin names which should be loaded, but failed.
        """
        failed_list = []
        for el in pkgutil.iter_modules([plugin_dir]):
            if plugin_dir != self.CORE_PLUGIN_DIR:
                if self.LOAD_PLUGINS and el[1] not in self.LOAD_PLUGINS:
                    continue
                if el[1] in self.NOT_LOAD_PLUGINS:
                    continue

            if not self.load_plugin(plugin_dir, el[1]):
                failed_list.append(el[1])
        return failed_list

    def _import_plugin(self, module_name):
        """
        Imports a plugin module

        :param module_name: The full qualified plugin module name to imported
        """
        module = pkgutil.importlib.import_module(module_name)
        members = inspect.getmembers(module)
        found = False
        for name, obj in members:
            if name == "Plugin":
                found = True
                obj(self)
        if not found:
            raise PluginClassNotFound(members)

    def load_plugin(self, plugin_dir, plugin_name):
        """
        Loads a plugin and performs instantiating and registering of the plugin

        :param plugin_dir: The directory from which the plugin will be loaded
        :param plugin_name: The name of the plugin module
        :return: `True` if plugin is loaded successfully, `False` on errors or `None` if plugin already loaded.
        """
        for pl in self.plugins:
            if pl.get_name() == plugin_name:
                logging.info("A Plugin called %s already loaded, skipping loading.", plugin_name)
                return None

        try:
            to_import = "{}.{}".format(plugin_dir, plugin_name)
            try:
                self._import_plugin(to_import)
            except PluginClassNotFound:
                to_import = "{0}.{1}.{1}".format(plugin_dir, plugin_name)
                self._import_plugin(to_import)

        except NotLoadable as e:
            logging.warning("Plugin %s could not be loaded: %s", plugin_name, e)
            plugin_instance = converters.get_plugin_by_name(plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False

        except PluginClassNotFound as e:
            logging.error("Unable to load plugin '%s': Plugin class not found", plugin_name)
            logging.debug("Members: %s", pprint.pformat(e.members))
            return False

        except (TypeError, Exception):
            logging.error("Unable to load plugin '%s':\n%s", plugin_name, traceback.format_exc())
            plugin_instance = converters.get_plugin_by_name(plugin_name)
            if plugin_instance is not None:
                self.deregister(plugin_instance)
            return False

        logging.info("Loaded plugin %s", plugin_name)
        if self.liveticker.restored:
            await self.liveticker.restore([plugin_name])
        return True

    def unload_plugin(self, plugin_name, save_config=True):
        """
        Unloads a plugin and performs plugin cleanup and saving the config and storage data

        :param plugin_name: The plugin name to be unloaded
        :param save_config: If `True` the plugin config and storage will be saved, on `False` not.
        :return: `True` if plugin was unloaded successfully, `False` on errors and `None` if plugin is not laoded.
        """
        try:
            plugin = converters.get_plugin_by_name(plugin_name)
            if plugin is None:
                return None

            self.loop.create_task(plugin.shutdown())
            if save_config:
                Config.save(plugin)
                Storage.save(plugin)
            self.liveticker.unload_plugin(plugin_name)

            self.deregister(plugin)

        except (TypeError, Exception):
            logging.error("Unable to unload plugin: %s:\n%s", plugin_name, traceback.format_exc())
            return False
        logging.info("Unloaded plugin %s", plugin_name)
        return True

    def set_debug_mode(self, mode: bool):
        """
        Enables or disables the debug mode

        :param mode: `True` to enable, `False` to disable debug mode
        """
        if mode == self.DEBUG_MODE:
            return

        if mode:
            self.DEBUG_MODE = True
        else:
            self.DEBUG_MODE = False

        logging.info("Debug mode set to %s", self.DEBUG_MODE)
        logging_setup(debug=mode)

    async def shutdown(self, status):
        """
        Shutting down the bot to handle the exit code by the runscript, e.g. for updating

        :param status: The exit status or exit code
        """
        try:
            status = status.value
        except AttributeError:
            pass
        self.timers.shutdown(status)
        logging.info("Shutting down.")
        logging.debug("Exit code: %s", status)
        sys.exit(status)

    async def on_error(self, event_method, *args, **kwargs):
        """
        Handles general errors occurring during execution and prints the exception data into the debug channel.
        In debug mode the exception will be handled by discord.py own on_error event method.

        :param event_method: The name of the event that raised the exception
        :param args: The positional arguments for the event that raised the exception
        :param kwargs: The keyword arguments for the event that raised the exception
        """
        if self.DEBUG_MODE:
            return await super().on_error(event_method, *args, **kwargs)

        exc_type, exc_value, exc_traceback = sys.exc_info()

        if (exc_type is commands.CommandNotFound
                or exc_type is commands.DisabledCommand):
            return

        embed = discord.Embed(title=':x: Error', colour=0xe74c3c)  # Red
        embed.add_field(name='Error', value=exc_type)
        embed.add_field(name='Event', value=event_method)
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

    async def on_command_error(self, context, exception):
        """
        Handles error occurring during execution of commands and prints the exception data into debug channel.
        In debug mode the exception will be handled by discord.py own on_command_error event method.

        :param context: The invocation context
        :param exception: The error that was raised
        """
        if self.DEBUG_MODE:
            return await super().on_command_error(context, exception)

        # No command or ignoring list handling
        if isinstance(exception, ignoring.UserBlockedCommand):
            await send_error_to_ctx(context, exception, default="{} has blocked the command `{}`.".
                                    format(converters.get_best_username(exception.user), exception.command))
        if isinstance(exception, (commands.CommandNotFound, commands.DisabledCommand)):
            return

        # Check Failures
        if isinstance(exception, (commands.MissingRole, commands.MissingAnyRole)):
            await send_error_to_ctx(context, exception, default="You don't have the required role for this command.")
        elif isinstance(exception, permchecks.WrongChannel):
            await send_error_to_ctx(context, exception,
                                    default="Command can only be used in channel {}".
                                    format(exception.channel))
        elif isinstance(exception, commands.NoPrivateMessage):
            await send_error_to_ctx(context, exception, default="Command can't be used in private messages.")
        elif isinstance(exception, commands.CheckFailure):
            await send_error_to_ctx(context, exception, default="Permission error.")

        # User input errors
        elif isinstance(exception, commands.MissingRequiredArgument):
            await send_error_to_ctx(context, exception, default="Required argument missing: {}".
                                    format(exception.param))
        elif isinstance(exception, commands.TooManyArguments):
            await send_error_to_ctx(context, exception, default="Too many arguments given.")
        elif isinstance(exception, commands.BadArgument):
            await send_error_to_ctx(context, exception, default="Argument don't have the required format: {}".
                                    format(exception))
        elif isinstance(exception, commands.UserInputError):
            await send_error_to_ctx(context, exception, default="Argument error for argument: {}".
                                    format(exception))

        # Other errors
        else:
            # error handling
            embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c)  # Red
            embed.add_field(name='Error', value=exception)
            embed.add_field(name='Command', value=context.command)
            embed.add_field(name='Message', value=context.message.clean_content)
            if isinstance(context.channel, discord.TextChannel):
                embed.add_field(name='Channel', value=context.channel.name)
            if isinstance(context.channel, discord.DMChannel):
                embed.add_field(name='Channel', value=context.channel.recipient)
            if isinstance(context.channel, discord.GroupChannel):
                embed.add_field(name='Channel', value=context.channel.recipients)
            embed.add_field(name='Author', value=context.author.display_name)
            embed.url = context.message.jump_url
            embed.timestamp = datetime.datetime.utcnow()

            # gather traceback
            ex_tb = "".join(traceback.TracebackException.from_exception(exception).format())
            is_tb_own_msg = len(ex_tb) > 2000
            if is_tb_own_msg:
                embed.description = "Exception Traceback see next message."
                ex_tb = stringutils.paginate(ex_tb.split("\n"), msg_prefix="```python\n", msg_suffix="```")
            else:
                embed.description = f"```python\n{ex_tb}```"

            # send messages
            await utils.write_debug_channel(embed)
            if is_tb_own_msg:
                for msg in ex_tb:
                    await utils.write_debug_channel(msg)
            await utils.add_reaction(context.message, Lang.CMDERROR)
            await send_error_to_ctx(context, exception, default="Unknown error while executing command.")

    async def on_message(self, message):
        """
        Basic message and ignore list handling

        :param message: The message which was written
        """

        # DM handling
        if message.guild is None:
            if await self.dm_listener.handle_dm(message):
                return

        # user on ignore list
        if self.ignoring.check_user(message.author):
            return

        # debug mode whitelist
        if not permchecks.debug_user_check(message.author):
            return

        await super().process_commands(message)

    async def command_disabled(self, ctx):
        """
        Checks if a command is disabled or blocked for user.
        This check will be executed before other command checks.

        :param ctx: The command context
        :returns: True if command can be executed, otherwise the `discord.ext.commands.DisabledCommand` exception
        """
        if self.ignoring.check_command(ctx):
            raise commands.DisabledCommand()
        if self.ignoring.check_active_usage(ctx.author, ctx.command.qualified_name):
            raise commands.DisabledCommand()
        if self.ignoring.check_passive_usage(ctx.author, ctx.command.qualified_name):
            raise commands.DisabledCommand()
        return True


def intent_setup():
    """Sets the intent settings to work correctly with the Discord API"""
    intents = discord.Intents.default()
    intents.members = True
    return intents


def logging_setup(debug=False):
    """
    Sets the logging level

    :param debug: If `True` the logging level will be set to `logging.DEBUG`, else to `logging.INFO`
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

    root_logger = logging.root
    for el in root_logger.manager.loggerDict:
        logger = logging.root.manager.loggerDict[el]
        if isinstance(logger, logging.PlaceHolder):
            continue
        if logger.name.startswith("discord."):
            logger.setLevel(logging.INFO)  # set discord.py logger always to info
        else:
            logger.setLevel(level)

    logging.log(level, "Logging level set to %s", level)


async def send_error_to_ctx(ctx: discord.ext.commands.Context,
                            error: Exception,
                            default="Unknown Error.",
                            message=""):
    """
    Sends an error to the command executing user. If the error contains a user_message attribute with content,
    its content will be send as message. Otherwise if the error contains a message in its
    Exception class member "args", the message in args[0] will be send. If a message is given,
    this message will be send no matter what the "args" member contains.

    :param ctx: The context to send the error message
    :param error: The error to send
    :param default: The default message
    :param message: The error dependent error message
    """
    if message:
        await ctx.send(message)
    elif hasattr(error, "user_message") and str(error.user_message):
        await ctx.send(str(error.user_message))
    elif len(error.args) > 0 and error.args[0] is not None and str(error.args[0]):
        await ctx.send(str(error.args[0]))
    else:
        await ctx.send(default)


def main():
    """Starts the Geckarbot"""

    injections.pre_injections()
    logging_setup()
    intents = intent_setup()
    bot = Geckarbot(command_prefix='!', intents=intents, case_insensitive=True)
    injections.post_injections(bot)
    logging.info("Loading core plugins")
    failed_plugins = bot.load_plugins(bot.CORE_PLUGIN_DIR)

    # pylint: disable=unused-variable
    @bot.event
    async def on_ready():
        """Loads plugins and prints on server that bot is ready"""
        guild = discord.utils.get(bot.guilds, id=bot.SERVER_ID)
        bot.guild = guild

        logging.info("Loading plugins")
        failed_plugins.extend(bot.load_plugins(bot.PLUGIN_DIR))

        if not bot.DEBUG_MODE:
            await bot.presence.start()

        logging.info("%s is connected to the following server: %s (id: %d)", bot.user, guild.name, guild.id)

        members = "\n - ".join([member.name for member in guild.members])
        logging.info("Server Members:\n - %s", members)

        await utils.write_debug_channel("Geckarbot {} connected on {} with {} users.".
                                        format(bot.VERSION, guild.name, len(guild.members)))
        subsys = bot.get_subsystem_list()
        await utils.write_debug_channel(f"Loaded {len(subsys)} subsystems: {', '.join(subsys)}")
        core_p = bot.get_coreplugins()
        await utils.write_debug_channel(f"Loaded {len(core_p)} coreplugins: {', '.join(core_p)}")
        plugins = bot.get_normalplugins()
        await utils.write_debug_channel(f"Loaded {len(plugins)} plugins: {', '.join(plugins)}")

        if len(failed_plugins) > 0:
            await utils.write_debug_channel("Failed loading {} plugins: {}".format(len(failed_plugins),
                                                                                   ', '.join(failed_plugins)))
        unloaded = bot.get_unloaded_plugins()
        if len(unloaded) > 0:
            await utils.write_debug_channel("{} additional plugins available: {}".format(len(unloaded),
                                                                                         ', '.join(unloaded)))

    bot.run(bot.TOKEN)


if __name__ == "__main__":
    main()
