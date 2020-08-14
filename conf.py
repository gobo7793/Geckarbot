import os
import json
import logging
import pkgutil
from botutils import jsonUtils
from base import Configurable


class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class PluginSlot:
    """Contains basic data for plugins"""

    def __init__(self, instance: Configurable, is_subsystem=False):
        self.instance = instance
        self.name = instance.__module__.rsplit(".", 1)[1]
        self.config = None
        self.is_subsystem = is_subsystem

        if not is_subsystem:
            self.storage_dir = "{}/{}".format(Config().STORAGE_DIR, self.name)

        self.lang = instance.get_lang()
        if self.lang is None:
            try:
                lang_module = pkgutil.importlib.import_module(
                    "{}.{}".format(self.storage_dir.replace('/', '.'), "lang"))
                self.lang = lang_module.lang
            except Exception as e:
                self.lang = {}
                logging.error("Unable to load lang file from plugin: {} ({})".format(self.name, e))
            pass


class Config(metaclass=_Singleton):

    ######
    # Basic bot info
    ######

    VERSION = "1.8.3"
    CONFIG_DIR = "config"
    PLUGIN_DIR = "plugins"
    CORE_PLUGIN_DIR = "coreplugins"
    STORAGE_DIR = "storage"

    BOT_CONFIG_FILE = "geckarbot"

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

    ######
    # Init
    ######

    def __init__(self):
        self.plugins = []

    def load_bot(self):
        bot_data = self._read_config_file(self.BOT_CONFIG_FILE)
        if bot_data is None:
            logging.critical("Cannot load bot.")
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

    ######
    # Read/Write config files
    ######

    def _write_config_file(self, file_name: str, config_data):
        """Writes the config to file_name.json and returns if successfull"""
        try:
            with open(f"{self.CONFIG_DIR}/{file_name}.json", "w") as f:
                json.dump(config_data, f, cls=jsonUtils.Encoder, indent=4)
                return True
        except (OSError, InterruptedError, OverflowError, ValueError, TypeError):
            logging.error(f"Error writing config file {self.CONFIG_DIR}/{file_name}.json")
            return False

    def _read_config_file(self, file_name: str):
        """Reads the file_name.json and returns the content or None if errors"""
        if not os.path.exists(f"{self.CONFIG_DIR}/{file_name}.json"):
            logging.info(f"Config file {self.CONFIG_DIR}/{file_name}.json not found.")
            return None
        else:
            try:
                with open(f"{self.CONFIG_DIR}/{file_name}.json", "r") as f:
                    jsondata = json.load(f, cls=jsonUtils.Decoder)
                    return jsondata
            except (OSError, InterruptedError, json.JSONDecodeError):
                logging.error(f"Error reading {self.CONFIG_DIR}/{file_name}.json.")
                return None

    ######
    # Save/Load/Get plugin config
    ######
    @classmethod
    def get(cls, plugin):
        """
        Returns the config of the given plugin.
        If given plugin is not registered, None will be returned.
        """
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                return plugin_slot.config
        return None

    @classmethod
    def set(cls, plugin, config):
        """
        Sets the config of the given plugin.
        """
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                plugin_slot.config = config

    @classmethod
    def save(cls, plugin):
        """Saves the config of the given plugin.
        If given plugin is not registered, None will be returned,
        else if saving is succesfully."""
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                return self._write_config_file(plugin_slot.name, plugin_slot.config)
        return None

    @classmethod
    def load(cls, plugin):
        """Loads the config of the given plugin.
        If given plugin is not registered, None will be returned, if errors
        occured during loading False and it's default config will be used
        as its config, otherwise True."""
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                loaded = self._read_config_file(plugin_slot.name)
                if loaded is None:
                    plugin_slot.config = plugin.default_config()
                    return False
                plugin_slot.config = loaded
                return True
        return None

    @classmethod
    def load_all(cls):
        """Loads the config of all registered plugins. If config of a
        plugin can't be loaded, its default config will be used as config."""
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance.can_reload:
                loaded = self._read_config_file(plugin_slot.name)
                if loaded is None:
                    loaded = plugin_slot.instance.default_config()
                plugin_slot.config = loaded

    ######
    # Lang/Strings/Resources
    ######
    @classmethod
    def storage_dir(cls, plugin):
        """Returns the storage directory for additional
        resources for the given plugin instance."""
        self = cls()
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                return plugin_slot.storage_dir
        return None

    @classmethod
    def lang(cls, plugin, str_name, *args):
        """
        Returns the given string from plugins language/string file.
        If language setted in Config().LANGUAGE_CODE is not supported, 'en' will be used.
        If str_name or the configured language code cannot be found, str_name will be returned.
        :param plugin: The plugin instance
        :param str_name: The name of the returning string.
            If not available for current language, an empty string will be returned.
        :param args: The strings to insert into the returning string via format()
        """
        self = cls()
        if len(args) == 0:
            args = [""]  # ugly lol

        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                if (self.LANGUAGE_CODE in plugin_slot.lang
                        and str_name in plugin_slot.lang[self.LANGUAGE_CODE]):
                    lang_code = self.LANGUAGE_CODE
                else:
                    lang_code = 'en'

                lang_str = plugin_slot.lang.get(lang_code, {}).get(str_name, str_name)
                return lang_str.format(*args)
        return str_name
