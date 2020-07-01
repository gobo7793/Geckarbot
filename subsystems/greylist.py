import discord

from conf import Config
from botutils import enums


class Greylist:
    """Manage the user greylist for using the bot.
    Users on greylist can't play the bot provided games on their greylist.
    """

    def __init__(self, plugin):
        self.plugin = plugin

    def gl_conf(self):
        return Config().get(self.plugin)['greylist']

    def add(self, user: discord.Member, game: enums.GreylistGames = None):
        """Adds the given game to users greylist.
        If game is None, all games will be added.
        If user is already on list, the user game list will be updated.
        If user is new on list, True will be returned, otherwise False.
        """
        if game is None:
            game = enums.GreylistGames.ALL
        was_added = True
        if self.is_user_on_greylist(user, game):
            game = self.gl_conf()[user.id] | game
            was_added = False
        self.gl_conf()[user.id] = game
        Config().save(self.plugin)
        return was_added

    def remove(self, user: discord.Member, game: enums.GreylistGames = None):
        """Removes the given game from users greylist.
        If game is None, all games will be removed.
        If user is not on list, None will be returned.
        If user was completely removed, True will be returned, otherwise False.
        """
        if game is None:
            game = enums.GreylistGames.ALL
        was_removed = None
        if self.is_user_on_greylist(user, game):
            self.gl_conf()[user.id] = self.gl_conf()[user.id] & ~game
            was_removed = False
            if self.gl_conf()[user.id] is enums.GreylistGames.No_Game:
                del (self.gl_conf()[user.id])
                was_removed = True
        Config().save(self.plugin)
        return was_removed

    def get_greylist_names(self):
        """Returns the greylisted members"""
        greylisted_members = ", ".join([self.plugin.bot.get_user(uid).name for uid in self.gl_conf()])
        return greylisted_members

    def is_user_on_greylist(self, user: discord.Member, game: enums.GreylistGames):
        """Returns if user is for the given game on the greylist"""
        return self.is_userid_on_greylist(user.id, game)

    def is_userid_on_greylist(self, userid: int, game: enums.GreylistGames):
        """Returns if user id is for the given game on the greylist"""
        if userid in self.gl_conf():
            if self.gl_conf()[userid] & game is not 0:
                return True
        return False
