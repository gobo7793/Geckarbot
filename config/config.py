# General config file
# Default values defined during json reading in read_config_file()
import os
import json
import datetime
from dotenv import load_dotenv
from botUtils import jsonUtils
from botUtils import enums

VERSION = "0.2.1"

# Reading .env server data
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID"))
DEBUG_CHAN_ID = int(os.getenv("DEBUG_CHAN_ID"))
DSC_CHAN_ID = int(os.getenv("DSC_CHAN_ID"))
DEBUG_MODE = os.getenv("DEBUG_MODE", False)

CONFIG_FILE = "config/config.json"

# Black/Greylisting
blacklist = []
greylist = {}

# DSC
dsc = {
    "ruleLink": None,
    "contestdocLink": None,
    "hostId": None,
    "state": None,
    "ytLink": None,
    "stateEnd": None
}


def write_config_file():
    """Writes the config to json file"""
    jsondata = {
        'blacklist': blacklist,
        'greylist': greylist,
        'dsc': dsc
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(jsondata, f, cls=jsonUtils.Encoder, indent=4)


def read_config_file():
    """Reads the config json file and returns if an error occured"""
    print("Loading config file")

    wasError = False
    jsondata = {}
    if not os.path.exists(CONFIG_FILE):
        print("No config file found. Using defaults.")
    else:
        try:
            with open(CONFIG_FILE, "r") as f:
                jsondata = json.load(f, object_hook=jsonUtils.decoder_obj_hook)
        except:
            print("Error reading json config data. Using defaults.")
            wasError = True

    # Black/Greylist
    blacklist = jsondata.get('blacklist', [])
    greylist = jsondata.get('greylist', {})

    # DSC
    dsc['ruleLink'] = jsondata.get('dsc', {}).get('ruleLink', "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg")
    dsc['contestdocLink'] = jsondata.get('dsc', {}).get('contestdocLink', "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8")
    dsc['hostId'] = jsondata.get('dsc', {}).get('hostId')
    dsc['state'] = jsondata.get('dsc', {}).get('state', enums.DscState.NA)
    dsc['ytLink'] = jsondata.get('dsc', {}).get('ytLink')
    dsc['stateEnd'] = jsondata.get('dsc', {}).get('stateEnd', datetime.datetime.now())

    return wasError
