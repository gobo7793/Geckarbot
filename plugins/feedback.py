from Geckarbot import BasePlugin


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        pass

        bot.register(self)
