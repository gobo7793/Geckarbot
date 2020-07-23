import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient
from conf import Config


class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

    def default_config(self):
        return {
            'matches_range': "Aktuell!B3:H11",
            'observed_users': [(64, 14), (76, 14), (68, 26), (68, 38), (70, 38)],
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8"
        }

    def spaetzle_conf(self):
        return Config().get(self)

    def get_api_client(self):
        return sheetsclient.Client(self.spaetzle_conf()['spaetzledoc_id'])

    @commands.group(name="spaetzle", aliases=["spätzle", "spatzle", "spätzles"], invoke_without_command=True, help="commands for managing the 'Spätzles-Tippspiel'")
    async def spaetzle(self, ctx):
        await ctx.invoke(self.bot.get_command('spaetzle info'))

    @spaetzle.command(name="info", help="Get info about the Spaetzles-Tippspiel")
    async def spaetzle_info(self, ctx):
        await ctx.send("Keine Spätzles. Nur Fußball :c")

    @spaetzle.command(name="scrape", help="Gets the data from the thread.")
    async def scrape(self, ctx, url):
        await ctx.send("Dieser cmd holt sich die Tipps automatisch aus dem angegebenen Forums-Thread! Also irgendwann "
                       "mal :c")

    @spaetzle.command(name="duels", aliases=["duelle"], help="Shows the duels of our people!")
    async def show_duels(self, ctx):
        msg = ""
        c = self.get_api_client()
        for col, row in self.spaetzle_conf()['observed_users']:
            """
            user = c.get_cell(col, row)
            opponent = c.get_cell(col + 1, row + 11)
            goalsH = c.get_cell(col, row + 10)
            goalsA = c.get_cell(col, row + 11)
            print(user, opponent, goalsH, goalsA)
            msg += "**{}** [{}:{}] {}\n".format(user, goalsH, goalsA, opponent)"""
            data = c.get("Aktuell!" + c.cellname(col, row) + ":" + c.cellname(col + 1, row + 11))
            msg += "**{}** [{}:{}] {}\n".format(data[0][0], data[10][0], data[11][0], data[11][1])

        await ctx.send(embed=discord.Embed(title="Duelle", description=msg))

    @spaetzle.command(name="matches", aliases=["spiele"], help="Displays the matches to be guessed")
    async def show_matches(self, ctx):
        c = self.get_api_client()
        matches = c.get(self.spaetzle_conf()['matches_range'])

        msg = ""
        for match in matches:
            msg += "{0} {1} {2} Uhr | {3} - {6} | {4}:{5}\n".format(*match)

        await ctx.send(embed=discord.Embed(title="Spiele", description=msg))
