from conf import Storage
from plugins.spaetzle.utils import get_user_cell, get_user_league, UserNotFound


class UserBridge:

    def __init__(self, plugin):
        self.plugin = plugin

    def get_user(self, ctx):
        if ctx.author.id in Storage().get(self.plugin)['discord_user_bridge']:
            return Storage().get(self.plugin)['discord_user_bridge'][ctx.author.id]
        else:
            return None

    def cut_bridge(self, ctx):
        user = ctx.author.id
        if user in Storage().get(self.plugin)["discord_user_bridge"]:
            del Storage().get(self.plugin)["discord_user_bridge"][user]
            Storage().save(self.plugin)
            return True
        else:
            return False

    def add_bridge(self, ctx, user):
        try:
            get_user_cell(self.plugin, user)
            Storage().get(self.plugin)["discord_user_bridge"][ctx.message.author.id] = user
            Storage().save(self.plugin)
            return True
        except UserNotFound:
            return False


class ObservedUsers:

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.users = Storage().get(plugin)['observed_users']

    def append(self, user):
        try:
            get_user_league(self.plugin, user)
        except UserNotFound:
            return False

        if user not in self.users:
            self.users.append(user)
            Storage().save(self.plugin)
        return True

    def remove(self, user):
        if user in self.users:
            self.users.remove(user)
            Storage().save(self.plugin)
            return True
        else:
            return False

    def get_all(self):
        return Storage().get(self.plugin)['observed_users']