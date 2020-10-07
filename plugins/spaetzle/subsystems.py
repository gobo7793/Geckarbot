from botutils.utils import add_reaction
from conf import Storage, Lang
from plugins.spaetzle.spaetzle import UserNotFound
from plugins.spaetzle.utils import get_user_cell


class UserBridge:

    def __init__(self, plugin):
        self.plugin = plugin

    async def get_user(self, ctx):
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