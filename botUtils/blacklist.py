import os
import json
import discord
from config import config


class blacklist(object):
    """Manage the user banlist for using the bot"""
    
    def __init__(self, bot):
        self.bot = bot

    def addUserToBlacklist(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.isUserOnBlacklist(user):
            config.blacklist.append(user.id)
            config.writeConfigFile()
            return True
        else:
            return False

    def delUserFromBlacklist(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.isUserOnBlacklist(user):
            config.blacklist.remove(user.id)
            config.writeConfigFile()
            return True
        else:
            return False

    def getBlacklist(self):
        """Returns the blacklisted member names"""
        blacklistedMembers = ", ".join([self.bot.get_user(id).name for id in config.blacklist])
        return blacklistedMembers

    def isUserOnBlacklist(self, user: discord.Member):
        """Returns if user is on bot blacklist"""
        return self.isUserIDOnBlacklist(user.id)

    def isUserIDOnBlacklist(self, userID: int):
        """Returns if user id is on bot blacklist"""
        if userID in config.blacklist:
            return True
        else:
            return False
