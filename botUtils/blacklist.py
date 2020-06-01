import os
import json
import discord
from config import config


class Blacklist(object):
    """Manage the user banlist for using the bot"""
    
    def __init__(self, bot):
        self.bot = bot

    def add_user(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.is_member_on_blacklist(user):
            config.blacklist.append(user.id)
            config.write_config_file()
            return True
        else:
            return False

    def del_user(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.is_member_on_blacklist(user):
            config.blacklist.remove(user.id)
            config.write_config_file()
            return True
        else:
            return False

    def get_blacklist_names(self):
        """Returns the blacklisted member names"""
        blacklisted_members = ", ".join([self.bot.get_user(id).name for id in config.blacklist])
        return blacklisted_members

    def is_member_on_blacklist(self, user: discord.Member):
        """Returns if user is on bot blacklist"""
        return self.is_userid_on_blacklist(user.id)

    def is_userid_on_blacklist(self, userID: int):
        """Returns if user id is on bot blacklist"""
        if userID in config.blacklist:
            return True
        else:
            return False
