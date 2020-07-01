import discord
from conf import Config


class Blacklist:
    """Manage the user banlist for using the bot"""

    def __init__(self, plugin):
        self.plugin = plugin

    def bl_conf(self):
        return Config().get(self.plugin)['blacklist']

    def add_user(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.is_member_on_blacklist(user):
            self.bl_conf().append(user.id)
            Config().save(self.plugin)
            return True
        else:
            return False

    def del_user(self, user: discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.is_member_on_blacklist(user):
            self.bl_conf().remove(user.id)
            Config().save(self.plugin)
            return True
        else:
            return False

    def get_blacklist_names(self):
        """Returns the blacklisted member names"""
        blacklisted_members = ", ".join([self.plugin.bot.get_user(uid).name for uid in self.bl_conf()])
        return blacklisted_members

    def is_member_on_blacklist(self, user: discord.Member):
        """Returns if user is on bot blacklist"""
        return self.is_userid_on_blacklist(user.id)

    def is_userid_on_blacklist(self, userid: int):
        """Returns if user id is on bot blacklist"""
        if userid in self.bl_conf():
            return True
        else:
            return False
