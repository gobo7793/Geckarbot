import os
import json
import discord
from config import config

class blacklist(object):
    """Manage the user banlist for using the bot"""
    
    def __init__(self, bot):
        self.bot = bot
        self._readBlacklistFile();

    def _readBlacklistFile(self):
        """Reads the blacklist file if exists and save the containing user ids in blacklistedUserIds"""
        if os.path.exists(config.blacklist_file):
            with open(config.blacklist_file, "r") as f:
                try:
                    config.blacklist = json.load(f)
                except:
                    pass

    def _writeBlacklistFile(self):
        """Writes the current blacklisted users ids in blacklistedUserIds to the blacklist file"""
        with open(config.blacklist_file, "w") as f:
            json.dump(config.blacklist, f)

    def addUserToBlacklist(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.isUserOnBlacklist(user):
            config.blacklist.append(user.id)
            self._writeBlacklistFile()
            return True
        else:
            return False

    def delUserFromBlacklist(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.isUserOnBlacklist(user):
            config.blacklist.remove(user.id)
            self._writeBlacklistFile()
            return True
        else:
            return False

    def getBlacklist(self):
        """Returns the blacklisted member names"""
        blacklistedMembers = ", ".join([self.bot.get_user(id).name for id in config.blacklist])
        return blacklistedMembers

    def isUserOnBlacklist(self, user:discord.Member):
        """Returns if user is on bot blacklist"""
        return isUserOnBlacklist(user.id)

    def isUserOnBlacklist(self, userID:int):
        """Returns if user id is on bot blacklist"""
        if userID in config.blacklist:
            return True
        else:
            return False;
