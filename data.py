import os
import json
import logging
from enum import Enum
from botutils import jsonutils

from base import NotFound


class Const(Enum):
    BASEFILE = 0


class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class ConfigurableData:
    def __init__(self, iodir, configurable):
        """
        Handles the data of a specific IODirectory-Configurable-combination.
        :param iodir: IODirectory
        :param configurable: Configurable
        """
        self.iodir = iodir()
        self.configurable = configurable
        self.base_structure = {}
        self._structures = {}

    def _filebase(self):
        return f"{self.iodir.directory}/{self.configurable.get_name()}"

    def _filepath(self, container=None):
        base = self._filebase()
        if container is None:
            return f"{base}.json"
        else:
            return f"{base}/{container}.json"

    def _mkdir(self):
        """
        Creates the data directory if it does not exist.
        :raises: RuntimeError if the directory exists but is not a directory.
        """
        directory = self._filebase()
        if os.path.exists(directory):
            if not os.path.isdir(directory):
                raise RuntimeError("Failed creating directory {}: Not a directory".format(directory))
            else:
                return
        else:
            os.mkdir(directory)

    def _write_file(self, config_data, container=None):
        """Writes the config to file_name.json and returns if successfull"""
        if container is not None:
            self._mkdir()
        try:
            with open(self._filepath(container=container), "w", encoding="utf-8") as f:
                json.dump(config_data, f, cls=jsonutils.Encoder, indent=4)
                return True
        except (OSError, InterruptedError, OverflowError, ValueError, TypeError):
            logging.error(f"Error writing config file {self._filepath(container=container)}")
            return False

    def _read_file(self, container=None, silent=False):
        """Reads the file_name.json and returns the content or None if errors"""
        if not os.path.exists(self._filepath(container=container)):
            return None
        else:
            try:
                with open(self._filepath(container=container), "r", encoding="utf-8") as f:
                    jsondata = json.load(f, cls=jsonutils.Decoder)
                    return jsondata
            except (IsADirectoryError, OSError, InterruptedError, json.JSONDecodeError):
                if not silent:
                    logging.error(f"Error reading {self._filepath(container=container)}.json.")
                return None

    def load(self):
        # Load default
        if os.path.exists(self._filepath()):
            self._structures[None] = self._read_file()
        else:
            self.get()

        # Load containers
        if os.path.exists(self._filebase()) and os.path.isdir(self._filebase()):
            for el in os.listdir(self._filebase()):
                if not el.endswith(".json"):
                    continue
                container = el[:-len(".json")]
                el = self._read_file(container=container, silent=True)
                if el is not None:
                    self._structures[container] = el

    def structures(self):
        return self._structures.keys()

    def has_structure(self, container=None):
        if container in self._structures:
            return True
        else:
            return False

    def get(self, container=None):
        if container in self._structures:
            return self._structures[container]
        else:
            r = self._read_file(container=container)
            if r is None:
                r = self.iodir.get_default(self.configurable, container=container)
            self.set(r, container=container)
            return r

    def set(self, data, container=None):
        self._structures[container] = data

    def save(self, container=None):
        self._write_file(self._structures[container], container=container)


class IODirectory(metaclass=_Singleton):
    """
    This class handles an instance-specific directory that contains plugin-generated files for each plugin.
    """
    def __init__(self):
        self._configurabledata = {}

    @property
    def directory(self):
        """
        To be overwritten.
        :return: Directory name that this class administers.
        """
        raise NotImplementedError

    @classmethod
    def get_default(cls, plugin, container=None):
        """
        To be overwritten.
        :param plugin: Plugin object whose default structure is to be retrieved
        :param container: Data container name
        :return: Default structure
        """
        raise NotImplementedError

    @classmethod
    def set_default(cls, configurable):
        configurable.complaints = configurable.default_storage()

    @classmethod
    def has_structure(cls, plugin):
        if cls() not in plugin.iodirs or plugin.iodirs[cls()] is None:
            return False
        else:
            return True

    """
    Save/Load/Get configurable data
    """
    @classmethod
    def data(cls, plugin):
        if plugin not in cls()._configurabledata:
            cls()._configurabledata[plugin] = ConfigurableData(cls, plugin)
        return cls()._configurabledata[plugin]

    @classmethod
    def get(cls, plugin, container=None):
        """
        Returns the config of the given plugin.
        :param plugin: Plugin object
        :param container: Container name
        """
        return cls.data(plugin).get(container=container)

    @classmethod
    def set(cls, plugin, structure, container=None):
        """
        Sets the structure of the given plugin.
        """
        return cls.data(plugin).set(structure, container=container)

    @classmethod
    def save(cls, plugin, container=None):
        """
        Saves the config of the given plugin.
        If given plugin is not registered, None will be returned,
        else if saving is succesfully.
        """
        return cls.data(plugin).save(container=container)

    @classmethod
    def load(cls, plugin):
        """
        Loads the managed file of the given plugin.
        If the given plugin is not registered, None will be returned, if errors
        occured during loading False and it's default config will be used
        as its config, otherwise True.
        """
        return cls.data(plugin).load()


class Config(IODirectory):
    def __init__(self):
        super().__init__()
        self._bot = None
        self._directory = None

    @property
    def bot(self):
        return self._bot

    @bot.setter
    def bot(self, bot):
        self._bot = bot
        self._directory = bot.CONFIG_DIR

    @property
    def ADMIN_CHAN_ID(self):
        return self.bot.ADMIN_CHAN_ID

    @property
    def DEBUG_CHAN_ID(self):
        return self.bot.DEBUG_CHAN_ID

    @property
    def MOD_CHAN_ID(self):
        return self.bot.MOD_CHAN_ID

    @property
    def BOT_ADMIN_ROLE_ID(self):
        return self.bot.BOT_ADMIN_ROLE_ID

    @property
    def SERVER_ADMIN_ROLE_ID(self):
        return self.bot.SERVER_ADMIN_ROLE_ID

    @property
    def MOD_ROLE_ID(self):
        return self.bot.MOD_ROLE_ID

    @property
    def ADMIN_ROLES(self):
        return self.bot.ADMIN_ROLES

    @property
    def MOD_ROLES(self):
        return self.bot.MOD_ROLES

    @property
    def directory(self):
        return self._directory

    @classmethod
    def resource_dir(cls, plugin):
        """Returns the resource directory for the given plugin instance."""
        for el in cls().bot.plugins:
            if el is plugin:
                return el.resource_dir
        return None

    @classmethod
    def get_default(cls, plugin, container=None):
        try:
            return plugin.default_config(container=container)
        except TypeError:
            if container is None:
                return plugin.default_config()
            else:
                raise


class Storage(IODirectory):
    def __init__(self):
        super().__init__()
        self._bot = None
        self._directory = None

    @property
    def bot(self):
        return self._bot

    @bot.setter
    def bot(self, bot):
        self._bot = bot
        self._directory = bot.STORAGE_DIR

    @property
    def directory(self):
        return self._directory

    @classmethod
    def get_default(cls, plugin, container=None):
        try:
            return plugin.default_storage(container=container)
        except TypeError:
            if container is None:
                return plugin.default_storage()
            else:
                raise


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
        self._bot = None
        self.directory = None
        self._cache = {}

    @property
    def bot(self):
        return self._bot

    @bot.setter
    def bot(self, bot):
        self._bot = bot
        self.directory = bot.LANG_DIR

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
        try:
            lang = configurable.get_lang()
        except NotFound:
            lang = None
        if lang is None:
            try:
                with open(f"{cls().directory}/{configurable.get_name()}.json", encoding="utf-8") as f:
                    lang = json.load(f)
            except (IsADirectoryError, FileNotFoundError, PermissionError, OSError):
                logging.warning("Language file not found or unable to open for plugin {}"
                                .format(configurable.get_name()))
                lang = {}
            except Exception as e:
                lang = {}
                logging.error("Uncaught exception while loading lang file from plugin {}: {}"
                              .format(configurable.get_name(), e))
        cls()._cache[configurable] = lang
        return lang

    @classmethod
    def lang_no_failsafe(cls, configurable, str_name, *args):
        """
        Returns the given string from configurable's lang file.
        If language sett in Config().LANGUAGE_CODE is not supported, 'en' will be used.
        If nothing is found, returns None.

        :param configurable: The Configurable instance
        :param str_name: The name of the returning string.
        :param args: The strings to insert into the returning string via format()
        :return The most applicable lang string for the given configurable and str_name. None if nothing is found.
        """
        lang = cls().read_from_cache(configurable)
        lang_code = None
        try:
            lang_code = configurable.get_lang_code()
        except NotFound:
            pass
        if lang_code is None:
            lang_code = cls().bot.LANGUAGE_CODE
        if lang_code not in lang or str_name not in lang[lang_code]:
            lang_code = cls().bot.DEFAULT_LANG

        langstr = lang.get(lang_code, {}).get(str_name, None)
        if langstr is not None:
            langstr = langstr.format(*args)
        return langstr

    @classmethod
    def lang(cls, configurable, str_name, *args) -> str:
        """
        Returns the given string from configurable's lang file.
        If language sett in Config().LANGUAGE_CODE is not supported, 'en' will be used.
        If str_name or the configured language code cannot be found, str_name will be returned.

        :param configurable: The Configurable instance
        :param str_name: The name of the returning string.
            If not available for current language, an empty string will be returned.
        :param args: The strings to insert into the returning string via format()
        :return The most applicable lang string for the given configurable and str_name. None if nothing is found.
        """
        if len(args) == 0:
            args = [""]  # ugly lol

        langstr = cls.lang_no_failsafe(configurable, str_name, *args)
        if langstr is None:
            langstr = str_name
        return langstr

    @classmethod
    def get_default(cls, plugin):
        return plugin.default_config()


def reconfigure(bot):
    """
    Loads the config of all registered plugins. If config of a
    plugin can't be loaded, its default config will be used as config.
    """
    for el in bot.plugins:
        if el.can_reload:
            bot.configure(el)
