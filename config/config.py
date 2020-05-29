# General config file

import datetime
from botUtils import enums

# Blacklisting
blacklist_file = "config/blacklist.json"
blacklist = []

# DSC
dsc_file = "config/dsc.json"
dsc = {
    "rule_link" : "https://docs.google.com/document/d/1xvkIPgLfFvm4CLwbCoUa8WZ1Fa-Z_ELPAtgHaSpEEbg/edit",
    "contestdoc_link" : "https://docs.google.com/spreadsheets/d/1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8/edit#gid=0",
    "hostId" : "",
    "state" : enums.DscState.NA,
    "yt_playlist_link" : "",
    "voting_end" : datetime.datetime.now()
}