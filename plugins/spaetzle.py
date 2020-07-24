import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient
from conf import Config

class UserNotFound(Exception):
    pass

class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        Config().save(self)

    def default_config(self):
        return {
            'matches_range': "Aktuell!B3:H11",
            'observed_users': ["Costamiri", "gobo77", "KDDanny41", "Laserdisc", "Serianoxx"],
            'participants': {
                'liga1': ["TN 1", "TN 2", "TN 3", "TN 4", "TN 5", "TN 6",
                          "TN 7", "TN 8", "TN 9", "TN 10", "TN 11", "TN 12",
                          "TN 13", "TN 14", "TN 15", "TN 16", "TN 17", "TN 18"],
                'liga2': ["TN 19", "TN 20", "Costamiri", "TN 22", "TN 23", "TN 24",
                          "TN 25", "TN 26", "gobo77", "TN 28", "TN 29", "TN 30",
                          "TN 31", "TN 32", "TN 33", "TN 34", "TN 35", "TN 36"],
                'liga3': ["TN 37", "TN 38", "TN 39", "TN 40", "KDDanny41", "TN 42",
                          "TN 43", "TN 44", "TN 45", "TN 46", "TN 47", "TN 48",
                          "TN 49", "TN 50", "TN 51", "TN 52", "TN 53", "TN 54"],
                'liga4': ["TN 55", "TN 56", "TN 57", "TN 58", "Laserdisc", "Serianoxx",
                          "TN 61", "TN 62", "TN 63", "TN 64", "TN 65", "TN 66",
                          "TN 67", "TN 68", "TN 69", "TN 70", "TN 71", "TN 72"],
            },
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8"
        }

    def spaetzle_conf(self):
        return Config().get(self)

    def get_api_client(self):
        return sheetsclient.Client(self.spaetzle_conf()['spaetzledoc_id'])

    def get_user_cell(self, user):
        """
        Returns the position of the user's title cell in the 'Tipps' section
        :return: (col, row) of the cell
        """
        participants = self.spaetzle_conf()['participants']
        if user in participants['liga1']:
            col = 60 + (2 * participants['liga1'].index(user))
            row = 2
        elif user in participants['liga2']:
            col = 60 + (2 * participants['liga2'].index(user))
            row = 14
        elif user in participants['liga3']:
            col = 60 + (2 * participants['liga3'].index(user))
            row = 26
        elif user in participants['liga4']:
            col = 60 + (2 * participants['liga4'].index(user))
            row = 38
        else:
            raise UserNotFound()
        return col, row

    @commands.group(name="spaetzle", aliases=["spätzle", "spatzle", "spätzles"], invoke_without_command=True,
                    help="commands for managing the 'Spätzles-Tippspiel'")
    async def spaetzle(self, ctx):
        await ctx.invoke(self.bot.get_command('spaetzle info'))

    @spaetzle.command(name="info", help="Get info about the Spaetzles-Tippspiel")
    async def spaetzle_info(self, ctx):
        await ctx.send("Keine Spätzles. Nur Fußball :c")

    @spaetzle.command(name="link", help="Get the link to the spreadsheet")
    async def spaetzle_doc_link(self, ctx):
        await ctx.send("<https://docs.google.com/spreadsheets/d/{}>".format(self.spaetzle_conf()['spaetzledoc_id']))

    @spaetzle.command(name="scrape", help="Gets the data from the thread.")
    async def scrape(self, ctx, url):
        await ctx.send("Dieser cmd holt sich die Tipps automatisch aus dem angegebenen Forums-Thread! Also irgendwann "
                       "mal :c")

    @spaetzle.command(name="duels", aliases=["duelle"], help="Shows the duels of our people!")
    async def show_duels(self, ctx):
        msg = ""
        c = self.get_api_client()
        data_ranges = []
        observed_users = self.spaetzle_conf()['observed_users']
        for user in observed_users:
            col, row = self.get_user_cell(user)
            data_ranges.append("Aktuell!{}".format(c.cellname(col, row)))
            data_ranges.append("Aktuell!{}:{}".format(c.cellname(col, row + 10), c.cellname(col + 1, row + 11)))
        data = c.get_multiple(data_ranges)
        for i in range(0, len(data_ranges), 2):
            user = data[i][0][0]
            opponent = data[i+1][1][1]
            if opponent in observed_users:
                if observed_users.index(opponent) > observed_users.index(user):
                    msg += "**{}** [{}:{}] **{}**\n".format(user, data[i + 1][0][0], data[i + 1][1][0], opponent)
            else:
                msg += "**{}** [{}:{}] {}\n".format(user, data[i+1][0][0], data[i+1][1][0], opponent)

        await ctx.send(embed=discord.Embed(title="Duelle", description=msg))

    @spaetzle.command(name="matches", aliases=["spiele"], help="Displays the matches to be guessed")
    async def show_matches(self, ctx):
        c = self.get_api_client()
        matches = c.get(self.spaetzle_conf()['matches_range'])

        msg = ""
        for match in matches:
            msg += "{0} {1} {2} Uhr | {3} - {6} | {4}:{5}\n".format(*match)

        await ctx.send(embed=discord.Embed(title="Spiele", description=msg))
