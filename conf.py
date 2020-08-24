import os
import json
import logging
from enum import Enum
from botutils import jsonutils, converters
from base import Configurable, ConfigurableType


class Const(Enum):
    BASEFILE = 0


class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class ConfigurableContainer:
    """
    Contains basic data for Configurables
    """
    def __init__(self, instance: Configurable, category=None):
        self.instance = instance
        self.name = instance.get_name()
        self.iodirs = {}
        self.type = instance.get_configurable_type()
        self.category = self.name if category is None else category

        if self.type == ConfigurableType.PLUGIN or self.type == ConfigurableType.COREPLUGIN:
            self.resource_dir = "{}/{}".format(Config().RESOURCE_DIR, self.name)


class IODirectory(metaclass=_Singleton):
    def __init__(self):
        self._plugins = []
        self.bot = None

    @property
    def directory(self):
        """
        To be overwritten.
        :return: Directory name that this class administers.
        """
        raise NotImplementedError

    @classmethod
    def get_default(cls, plugin):
        """
        To be overwritten.
        :param plugin: Plugin object whose default structure is to be retrieved
        :return: Default structure
        """
        raise NotImplementedError

    @classmethod
    def set_default(cls, plugin_cnt):
        plugin_cnt.storage = plugin_cnt.instance.default_storage()

    @classmethod
    def has_structure(cls, plugin):
        cnt = converters.get_plugin_container(cls().bot, plugin)
        if cnt is None:
            raise RuntimeError("PANIC: {} ({}) is not a registered plugin".format(plugin, plugin.get_name()))
        if cls() not in cnt.iodirs or cnt.iodirs[cls()] is None:
            return False
        else:
            return True

    @classmethod
    def has_file(cls, plugin):
        """
        :param plugin: Plugin object
        :return: Returns whether `plugin` has a file.
        """
        return os.path.exists(cls()._filepath(plugin.get_name))

    @classmethod
    def _filepath(cls, file_name):
        return f"{cls().directory}/{file_name}.json"

    def _write_file(self, file_name: str, config_data):
        """Writes the config to file_name.json and returns if successfull"""
        try:
            with open(self._filepath(file_name), "w", encoding="utf-8") as f:
                json.dump(config_data, f, cls=jsonutils.Encoder, indent=4)
                return True
        except (OSError, InterruptedError, OverflowError, ValueError, TypeError):
            logging.error(f"Error writing config file {self._filepath(file_name)}.json")
            return False

    def _read_file(self, file_name: str):
        """Reads the file_name.json and returns the content or None if errors"""
        if not os.path.exists(self._filepath(file_name)):
            return None
        else:
            try:
                with open(self._filepath(file_name), "r", encoding="utf-8") as f:
                    jsondata = json.load(f, cls=jsonutils.Decoder)
                    return jsondata
            except (IsADirectoryError, OSError, InterruptedError, json.JSONDecodeError):
                logging.error(f"Error reading {self._filepath(file_name)}.json.")
                return None

    ######
    # Save/Load/Get plugin config
    ######
    @classmethod
    def get(cls, plugin):
        """
        Returns the config of the given plugin.
        If given plugin is not registered, None will be returned.
        :param plugin: Plugin object
        """
        for plugin_cnt in cls().bot.plugins:
            if plugin_cnt.instance is plugin:
                if cls() not in plugin_cnt.iodirs:
                    plugin_cnt.iodirs[cls()] = cls().get_default(plugin_cnt.instance)
                return plugin_cnt.iodirs[cls()]
        return None

    @classmethod
    def set(cls, plugin, structure):
        """
        Sets the structure of the given plugin.
        """
        self = cls()
        for plugin_cnt in self.bot.plugins:
            if plugin_cnt.instance is plugin:
                plugin_cnt.iodirs[cls()] = structure

    @classmethod
    def save(cls, plugin):
        """
        Saves the config of the given plugin.
        If given plugin is not registered, None will be returned,
        else if saving is succesfully.
        """
        for plugin_slot in cls().bot.plugins:
            if plugin_slot.instance is plugin:
                return cls()._write_file(plugin_slot.name, cls.get(plugin))
        return None

    @classmethod
    def load(cls, plugin):
        """
        Loads the managed file of the given plugin.
        If given plugin is not registered, None will be returned, if errors
        occured during loading False and it's default config will be used
        as its config, otherwise True.
        """
        for plugin_cnt in cls().bot.plugins:
            if plugin_cnt.instance is plugin:
                loaded = cls()._read_file(plugin_cnt.name)
                if loaded is None:
                    cls.set_default(plugin_cnt)
                    return False
                plugin_cnt.iodirs[cls()] = loaded
                return True
        return None


class Config(IODirectory):

    ######
    # Basic bot info
    ######
    VERSION = "1.8.3"
    CONFIG_DIR = "config"
    PLUGIN_DIR = "plugins"
    CORE_PLUGIN_DIR = "coreplugins"
    STORAGE_DIR = "storage"
    RESOURCE_DIR = "resource"
    LANG_DIR = "lang"
    BOT_CONFIG_FILE = "geckarbot"  # .json is implied

    def load_bot_config(self):
        """
        Bot init
        """
        bot_data = self._read_file(self.BOT_CONFIG_FILE)
        if bot_data is None:
            logging.critical("Unable to load bot config.")
        else:
            self.TOKEN = bot_data.get('DISCORD_TOKEN', 0)
            self.SERVER_ID = bot_data.get('SERVER_ID', 0)
            self.CHAN_IDS = bot_data.get('CHAN_IDS', {})
            self.ROLE_IDS = bot_data.get('ROLE_IDS', {})

            self.ADMIN_CHAN_ID = self.CHAN_IDS.get('admin', 0)
            self.DEBUG_CHAN_ID = self.CHAN_IDS.get('debug', self.CHAN_IDS.get('bot-interna', 0))
            self.ADMIN_ROLE_ID = self.ROLE_IDS.get('admin', 0)
            self.BOTMASTER_ROLE_ID = self.ROLE_IDS.get('botmaster', 0)

            self.DEBUG_MODE = bot_data.get('DEBUG_MODE', False)
            self.DEBUG_WHITELIST = bot_data.get('DEBUG_WHITELIST', [])

            self.GOOGLE_API_KEY = bot_data.get('GOOGLE_API_KEY', "")

            self.FULL_ACCESS_ROLES = [self.ADMIN_ROLE_ID, self.BOTMASTER_ROLE_ID]
            self.LANGUAGE_CODE = bot_data.get('LANG', 'en')

    @property
    def directory(self):
        return self.CONFIG_DIR

    @classmethod
    def resource_dir(cls, plugin):
        """Returns the resource directory for the given plugin instance."""
        for plugin_slot in cls().bot.plugins:
            if plugin_slot.instance is plugin:
                return plugin_slot.resource_dir
        return None
    
    @classmethod
    def get_default(cls, plugin):
        return plugin.default_config()


class Storage(IODirectory):
    @property
    def directory(self):
        return Config().STORAGE_DIR

    @classmethod
    def get_default(cls, plugin):
        return plugin.default_storage()


class Lang(metaclass=_Singleton):
    # Random Emoji collection
    EMOJI = {
        "success": "✅",
        "error": "❌",
        "nochange": "🤷‍♀️",
        "lettermap": [
            "🇦",  # a
            "🇧",  # b
            "🇨",  # c
            "🇩",  # d
            "🇪",  # e
            "🇫",  # f
            "🇬",  # g
            "🇭",  # h
            "🇮",  # i
            "🇯",  # j
            "🇰",  # k
            "🇱",  # l
            "🇲",  # m
            "🇳",  # n
            "🇴",  # o
            "🇵",  # p
            "🇶",  # q
            "🇷",  # r
            "🇸",  # s
            "🇹",  # t
            "🇺",  # u
            "🇻",  # v
            "🇼",  # w
            "🇽",  # x
            "🇾",  # y
            "🇿",  # z
        ],
    }
    CMDSUCCESS = EMOJI["success"]
    CMDERROR = EMOJI["error"]
    CMDNOCHANGE = EMOJI["nochange"]
    CMDNOPERMISSIONS = EMOJI["error"]  # todo find something better

    def __init__(self):
        self.bot = None
        self.directory = Config().LANG_DIR
        self._cache = {}

    @classmethod
    def clear_cache(cls):
        cls()._cache = {}

    @classmethod
    def remove_from_cache(cls, configurable):
        if configurable in cls()._cache:
            del cls()._cache[configurable]

    @classmethod
    def read_from_cache(cls, configurable):
        # Read from cache
        if configurable in cls()._cache:
            return cls()._cache[configurable]

        # Read from file or configurable
        lang = configurable.get_lang()
        if lang is None:
            try:
                with open(f"{Config().LANG_DIR}/{configurable.get_name()}.json", encoding="utf-8") as f:
                    lang = json.load(f)
            except (IsADirectoryError, FileNotFoundError, PermissionError, OSError):
                lang = {}
            except Exception as e:
                lang = {}
                logging.error("Uncaught exception while loading lang file from plugin {}: {}"
                              .format(configurable.get_name(), e))
            pass
        cls()._cache[configurable] = lang
        return lang

    @classmethod
    def lang(cls, configurable, str_name, *args):
        """
        Returns the given string from configurable's lang file.
        If language sett in Config().LANGUAGE_CODE is not supported, 'en' will be used.
        If str_name or the configured language code cannot be found, str_name will be returned.
        :param configurable: The Configurable instance
        :param str_name: The name of the returning string.
            If not available for current language, an empty string will be returned.
        :param args: The strings to insert into the returning string via format()
        """
        if len(args) == 0:
            args = [""]  # ugly lol

        lang = cls().read_from_cache(configurable)
        if Config().LANGUAGE_CODE in lang and str_name in lang[Config().LANGUAGE_CODE]:
            lang_code = Config().LANGUAGE_CODE
        else:
            lang_code = 'en'

        return lang.get(lang_code, {}).get(str_name, str_name).format(*args)

    @classmethod
    def get_default(cls, plugin):
        return plugin.default_config()


def reconfigure(bot):
    """
    Loads the config of all registered plugins. If config of a
    plugin can't be loaded, its default config will be used as config.
    """
    for plugin_slot in bot.plugins:
        if plugin_slot.instance.can_reload:
            bot.configure(plugin_slot.instance)
