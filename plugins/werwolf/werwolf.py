from discord.ext import commands

from base import BasePlugin
from subsystems.helpsys import DefaultCategories

from controller import Controller
from interface import Interface, GameLog


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        bot.register(self, DefaultCategories.GAMES)

    async def configure(self, ctx):
        pass

    async def acquire_participants(self, ctx):
        pass

    @commands.group(name="werwolf", invoke_without_command=True)
    async def cmd_werwolf(self, ctx):
        participants = await self.acquire_participants(ctx)
        config = await self.configure(ctx)
        interface = Interface()
        gamelog = GameLog()

        controller = Controller(config, participants, interface, gamelog)
        await controller.run()


