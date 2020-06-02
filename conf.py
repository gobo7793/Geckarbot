# General config
# Default values defined during json reading in read_config_file()
import os
import dotenv
import json
import datetime
from botUtils import jsonUtils, enums


class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Config(metaclass=_Singleton):

######
# Basic bot info
######

    VERSION = "1.0.2"
    CONFIG_FILE = "config/config.json"
    PLUGINDIR = "plugins"

######
# Init
######

    def __init__(self, *args, **kwargs):
        self.load_env()

    def load_env(self):
        """Reads general server data stored in .env"""
        dotenv.load_dotenv()
        self.TOKEN = os.getenv("DISCORD_TOKEN")
        self.DEBUG_MODE = os.getenv("DEBUG_MODE", False)
        self.DEBUG_USER_ID_REACTING = int(os.getenv("DEBUG_USER_ID_REACTING", 0))

        self.SERVER_ID = int(os.getenv("SERVER_ID"))
        self.DEBUG_CHAN_ID = int(os.getenv("DEBUG_CHAN_ID"))

######
# Configuration data
######

    # Server settings
    server_channels = { # Currently must be setted in Config().json manually
        'music': 0,
    }

    blacklist = []
    greylist = {}

    # DSC
    dsc = {
        'rule_link': None,
        'contestdoc_link': None,
        'host_id': None,
        'state': None,
        'yt_link': None,
        'state_end': None
    }

######
# Read/Write config
######

    def write_config_file(self):
        """Writes the config to json file"""
        jsondata = {
            'server_channels': self.server_channels,
            'blacklist': self.blacklist,
            'greylist': self.greylist,
            'dsc': self.dsc
        }

        with open(self.CONFIG_FILE, "w") as f:
            json.dump(jsondata, f, cls=jsonUtils.Encoder, indent=4)

    def read_config_file(self):
        """Reads the config json file and returns if an error occured"""
        print("Loading config file")

        wasError = False
        jsondata = {}
        if not os.path.exists(self.CONFIG_FILE):
            print("No config file found. Using defaults.")
        else:
            try:
                with open(self.CONFIG_FILE, "r") as f:
                    jsondata = json.load(f, object_hook=jsonUtils.decoder_obj_hook)
            except:
                print("Error reading json config data. Using defaults.")
                wasError = True

        # Server settings
        self.server_channels['music'] = jsondata.get('server_channels', {}).get('music', 0)
        self.blacklist = jsondata.get('blacklist', [])
        self.greylist = {int(k):v for k, v in jsondata.get('greylist', {}).items()}

        # DSC
        self.dsc['rule_link'] = jsondata.get('dsc', {}).get('rule_link', "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg")
        self.dsc['contestdoc_link'] = jsondata.get('dsc', {}).get('contestdoc_link', "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8")
        self.dsc['host_id'] = jsondata.get('dsc', {}).get('host_id')
        self.dsc['state'] = jsondata.get('dsc', {}).get('state', enums.DscState.NA)
        self.dsc['yt_link'] = jsondata.get('dsc', {}).get('yt_link')
        self.dsc['state_end'] = jsondata.get('dsc', {}).get('state_end', datetime.datetime.now())

        return wasError
