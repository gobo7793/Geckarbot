import os
import json
import discord
from config.config import Config


class Blacklist(object):
    """Manage the user banlist for using the bot"""
    
    def __init__(self, bot):
        self.bot = bot

    def add_user(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.is_member_on_blacklist(user):
            Config().blacklist.append(user.id)
            Config().write_config_file()
            return True
        else:
            return False

    def del_user(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.is_member_on_blacklist(user):
            Config().blacklist.remove(user.id)
            Config().write_config_file()
            return True
        else:
            return False

    def get_blacklist_names(self):
        """Returns the blacklisted member names"""
        blacklisted_members = ", ".join([self.bot.get_user(id).name for id in Config().blacklist])
        return blacklisted_members

    def is_member_on_blacklist(self, user: discord.Member):
        """Returns if user is on bot blacklist"""
        return self.is_userid_on_blacklist(user.id)

    def is_userid_on_blacklist(self, userID: int):
        """Returns if user id is on bot blacklist"""
        if userID in Config().blacklist:
            return True
        else:
            return False
