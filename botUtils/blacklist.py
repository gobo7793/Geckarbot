import os
import json
import discord

class blacklist(object):
    """Manage the user banlist for using the bot"""

    _blacklistFileName = "blacklist.json"
    blacklist_list = []

    def __init__(self, bot):
        self.bot = bot
        self.readBlacklistFile();

    def readBlacklistFile(self):
        """Reads the blacklist file if exists and save the containing user ids in blacklistedUserIds"""
        if os.path.exists(self._blacklistFileName):
            with open(self._blacklistFileName, "r") as f:
                try:
                    self.blacklist_list = json.load(f)
                except:
                    self.blacklist_list = []

    def writeBlacklist(self):
        """Writes the current blacklisted users ids in blacklistedUserIds to the blacklist file"""
        with open(self._blacklistFileName, "w") as f:
            json.dump(self.blacklist_list, f)

    def addUserToBlacklist(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.isUserOnBlacklist(user):
            self.blacklist_list.append(user.id)
            self.writeBlacklist()
            return True
        else:
            return False

    def delUserFromBlacklist(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.isUserOnBlacklist(user):
            self.blacklist_list.remove(user.id)
            self.writeBlacklist()
            return True
        else:
            return False

    def getBlacklist(self):
        """Returns the blacklisted member names"""
        blacklistedMembers = ", ".join([self.bot.get_user(id).name for id in self.blacklist_list])
        return blacklistedMembers

    def isUserOnBlacklist(self, user:discord.Member):
        """Returns if user is on bot blacklist"""
        if user.id in self.blacklist_list:
            return True
        else:
            return False;
