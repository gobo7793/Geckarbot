import os
import json
import datetime
import logging
from botutils import jsonUtils, enums


class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class PluginSlot():
    """Contains basic data for plugins"""

    def __init__(self, instance):
        self.instance = instance
        self.module_name = instance.__module__
        self.config = None


class Config(metaclass=_Singleton):

    ######
    # Basic bot info
    ######

    VERSION = "1.1.0"
    CONFIG_DIR = "config"
    PLUGIN_DIR = "plugins"
    CORE_PLUGIN_DIR = "coreplugins"

    BOT_CONFIG_FILE = "geckarbot"

    ######
    # Init
    ######

    def __init__(self, *args, **kwargs):
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

            self.DEBUG_CHAN_ID = self.CHAN_IDS.get('bot-interna', 0)
            self.ADMIN_ROLE_ID = self.ROLE_IDS.get('admin', 0)
            self.BOTMASTER_ROLE_ID = self.ROLE_IDS.get('botmaster', 0)

            self.DEBUG_MODE = bot_data.get('DEBUG_MODE', False)
            self.DEBUG_WHITELIST = bot_data.get('DEBUG_WHITELIST', [])

    ######
    # Read/Write config files
    ######

    def _write_config_file(self, file_name: str, config_data):
        """Writes the config to file_name.json and returns if successfull"""
        try:
            with open(f"{self.CONFIG_DIR}/{file_name}.json", "w") as f:
                json.dump(config_data, f, cls=jsonUtils.Encoder, indent=4)
                return True
        except:
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
                    jsondata = json.load(f, object_hook=jsonUtils.decoder_obj_hook)
                    return jsondata
            except:
                logging.error("Error reading {self.CONFIG_DIR}/{file_name}.json.")
                return None

    ######
    # Save/Load/Get plugin config
    ######

    def get(self, plugin):
        """Returns the config of the given plugin.
        If given plugin is not registered, None will be returned."""
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                return plugin_slot.config
        return None

    def save(self, plugin):
        """Saves the config of the given plugin.
        If given plugin is not registered, None will be returned,
        else if saving is succesfully."""
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                return self._write_config_file(plugin_slot.module_name, plugin_slot.config)
        return None

    def load(self, plugin):
        """Loads the config of the given plugin.
        If given plugin is not registered, None will be returned, if errors
        occured during loading False and an empty dictionary will be saved
        as its config, otherwise True."""
        for plugin_slot in self.plugins:
            if plugin_slot.instance is plugin:
                loaded = self._read_config_file(plugin_slot.module_name)
                if loaded is None:
                    plugin_slot.config = {}
                    return False
                plugin_slot.config = loaded
                return True
        return None

    def load_all(self):
        """Loads the config of all registered plugins. If config of a
        plugin can't be loaded, a empty dict will be saved as config."""
        return_value = True
        for plugin_slot in self.plugins:
            loaded = self._read_config_file(plugin_slot.module_name)
            if loaded is None:
                plugin_slot.config = {}
            plugin_slot.config = loaded
