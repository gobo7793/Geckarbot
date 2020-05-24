import discord
from discord.ext import commands

class sportCommands(commands.Cog, name="Sport Commands"):
    """Sport related commands"""

    def __init__(self, bot):
        self.bot = bot
        self._last_member = None

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de", pass_context=True)
    async def nine_nine(self, ctx):
        linklist=("Tabelle Bundesliga: https://www.kicker.de/1-bundesliga/tabelle\n"
                  "Tabelle 2. Bundesliga: https://www.kicker.de/2-bundesliga/tabelle\n"
                  "Tabelle 3. Liga: https://www.kicker.de/3-liga/tabelle\n"
                  "Tabelle AT-Bundesliga: https://www.kicker.de/tipp3-bundesliga/tabelle")
        await ctx.send(linklist)
