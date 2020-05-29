# General (default) config file

import os
import datetime
from dotenv import load_dotenv
from botUtils import enums

VERSION="0.1.1"


# Reading .env server data
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME")
DEBUG_MODE = os.getenv("DEBUG_MODE", False)
DEBUG_CHAN_ID = int(os.getenv("DEBUG_CHAN_ID"))
DSC_CHAN_ID = int(os.getenv("DSC_CHAN_ID"))

# Blacklisting
blacklist_file = "config/blacklist.json"
blacklist = []

# DSC
dsc_file = "config/dsc.json"
dsc = {
    "rule_link" : "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg/edit",
    "contestdoc_link" : "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8/edit#gid=0",
    "hostId" : None,
    "state" : enums.DscState.NA,
    "yt_playlist_link" : None,
    "state_end" : datetime.datetime.now()
}