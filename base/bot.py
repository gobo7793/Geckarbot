from enum import Enum
from typing import Optional, Union, List
from abc import abstractmethod

import discord
from discord.ext.commands import Bot

from services import helpsys
from services.ignoring import Ignoring
from services.liveticker import Liveticker
from services.presence import Presence
from services.reactions import ReactionListener
from services.dmlisteners import DMListener
from services.timers import Mothership


class Exitcode(Enum):
    """
    These exit codes are evaluated by the runscript and acted on accordingly.
    """
    SUCCESS = 0  # regular shutdown, doesn't come back up
    ERROR = 1  # some generic error
    HTTP = 2  # no connection to discord (not implemented)
    UNDEFINED = 3  # if this is returned, the exit code was not set correctly
    UPDATE = 10  # shutdown, update, restart
    RESTART = 11  # simple restart


class BaseBot(Bot):

    """
    Basic bot info
    """
    NAME: str = None
    VERSION: str = None
    PLUGIN_DIR: str = "plugins"
    CORE_PLUGIN_DIR: str = "coreplugins"
    CONFIG_DIR: str = "config"
    STORAGE_DIR: str = "storage"
    LANG_DIR: str = "lang"
    RESOURCE_DIR: str = "resource"
    DEFAULT_LANG: str = "en_US"

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
    WOLFRAMALPHA_API_KEY = None
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
        super().__init__(*args, **kwargs)

        self.guild: Optional[discord.Guild] = None

        self.reaction_listener: Optional[ReactionListener] = None
        self.dm_listener: Optional[DMListener] = None
        self.timers: Optional[Mothership] = None
        self.ignoring: Optional[Ignoring] = None
        self.helpsys: Optional[helpsys.GeckiHelp] = None
        self.presence: Optional[Presence] = None
        self.liveticker: Optional[Liveticker] = None

    @property
    @abstractmethod
    def plugins(self) -> list:
        pass

    @abstractmethod
    def plugin_objects(self, plugins_only: bool = False):
        pass

    @abstractmethod
    def get_coreplugins(self) -> List[str]:
        pass

    @abstractmethod
    def get_normalplugins(self) -> List[str]:
        pass

    @abstractmethod
    def get_all_available_plugins(self) -> List[str]:
        pass

    @abstractmethod
    def get_unloaded_plugins(self) -> List[str]:
        pass

    @staticmethod
    @abstractmethod
    def get_service_list() -> List[str]:
        pass

    @abstractmethod
    def register(self, plugin, category: Union[str, helpsys.DefaultCategories, helpsys.HelpCategory, None] = None,
                 category_desc: str = None) -> bool:
        pass

    @abstractmethod
    def unload_plugin(self, plugin_name: str, save_config: bool = True) -> Optional[bool]:
        pass

    @abstractmethod
    def load_plugin(self, plugin_dir: str, plugin_name: str) -> Optional[bool]:
        pass

    @abstractmethod
    def set_debug_mode(self, debug: bool):
        pass

    @abstractmethod
    async def shutdown(self, status: Exitcode):
        pass
