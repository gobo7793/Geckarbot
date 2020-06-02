import os
import json
import discord
from conf import Config
from botUtils.enums import GreylistGames


class Greylist(object):
    """Manage the user greylist for using the bot.
    Users on greylist can't play the bot provided games on their greylist.
    """
    
    def __init__(self, bot):
        self.bot = bot

    def add(self, user: discord.Member, game: GreylistGames = None):
        """Adds the given game to users greylist.
        If game is None, all games will be added.
        If user is already on list, the user game list will be updated.
        If user is new on list, True will be returned, otherwise False.
        """
        if game is None:
            game = GreylistGames.ALL
        was_added = True
        if self.is_user_on_greylist(user, game):
            game = Config().greylist[user.id] | game
            was_added = False
        Config().greylist[user.id] = game
        Config().write_config_file()
        return was_added

    def remove(self, user:discord.Member, game: GreylistGames = None):
        """Removes the given game from users greylist.
        If game is None, all games will be removed.
        If user is not on list, None will be returned.
        If user was completely removed, True will be returned, otherwise False.
        """
        if game is None:
            game = GreylistGames.ALL
        was_removed = None
        if self.is_user_on_greylist(user, game):
            Config().greylist[user.id] = Config().greylist[user.id] & ~game
            was_removed = False
            if Config().greylist[user.id] is GreylistGames.No_Game:
                del(Config().greylist[user.id])
                was_removed = True
        Config().write_config_file()
        return was_removed

    def get_greylist_names(self):
        """Returns the greylisted members"""
        greylisted_members = ", ".join([self.bot.get_user(id).name for id in Config().greylist])
        return greylisted_members

    def is_user_on_greylist(self, user:discord.Member, game: GreylistGames):
        """Returns if user is for the given game on the greylist"""
        return self.is_userid_on_greylist(user.id, game)

    def is_userid_on_greylist(self, userID: int, game: GreylistGames):
        """Returns if user id is for the given game on the greylist"""
        if userID in Config().greylist:
            if Config().greylist[userID] & game is not 0:
                return True
        return False
