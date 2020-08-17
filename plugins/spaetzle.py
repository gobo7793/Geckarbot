from datetime import datetime
from enum import Enum
from typing import Tuple

import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient
from conf import Storage, Lang

lang = {
    'en': {
        'info': "The Spaetzle(s)-Tippspiel is a prediction game where you compete in duels",
        'invalid_league': "Invalid League. Valid Leagues: 1, 2, 3, 4",
        'no_matches': "No matches found.",
        'user_not_bridged': "You are currently not connected with a user.",
        'user_not_found': "User not found."
    },
    'de': {
        'info': "Das Spätzle(s)-Tippspiel ist ein Tippspiel aus dem Stuttgarter TM-Forum in dem die Teilnehmer nicht "
                "nur Bundesligaspiele tippen, sondern damit in Duellen gegeneinander antreten.",
        'no_matches': "Keine Spiele gefunden."
    }
}

teams = {
    "FC Bayern München": "FCB",
    "Borussia Dortmund": "BVB",
    "Rasenballsport Leipzig": "LPZ",
    "Bor. Mönchengladbach": "BMG",
    "Bayer 04 Leverkusen": "LEV",
    "TSG Hoffenheim": "HOF",
    "VfL Wolfsburg": "WOB",
    "SC Freiburg": "SCF",
    "SG Eintracht Frankfurt": "SGE",
    "Hertha BSC": "BSC",
    "FC Union Berlin": "FCU",
    "FC Schalke 04": "S04",
    "FSV Mainz 05": "M05",
    "1. FC Köln": "KOE",
    "FC Augsburg": "FCA",
    "SV Werder Bremen": "SVW",
    "DSC Arminia Bielefeld": "DSC",
    "VfB Stuttgart": "VFB"
}


class UserNotFound(Exception):
    pass


class MatchStatus(Enum):
    CLOSED = ":ballot_box_with_check:"
    RUNNING = ":green_square:"
    UPCOMING = ":clock330:"
    UNKNOWN = ":grey_question:"


class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)
        Storage().save(self)

    def default_storage(self):
        return {
            'matches_range': "Aktuell!B3:H11",
            'observed_users': [],
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
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8",
            'discord_user_bridge': {}
        }

    def get_lang(self):
        return lang

    def spaetzle_lang(self, str_name, *args):
        return Lang.lang(self, str_name, *args)

    def spaetzle_conf(self):
        return Storage().get(self)

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
            raise UserNotFound
        return col, row

    def get_user_league(self, user):
        """
        Returns the league of the user
        :return: number of the league
        """
        participants = self.spaetzle_conf()['participants']
        if user in participants['liga1']:
            return 1
        elif user in participants['liga2']:
            return 2
        elif user in participants['liga3']:
            return 3
        elif user in participants['liga4']:
            return 4
        else:
            raise UserNotFound

    def convert_team_name(self, team):
        """
        Switch between die short and long version of a team name
        """
        return teams[team]

    def get_bridged_user(self, user_id):
        """
        Bridge between a Discord user and a Spätzle participant
        """
        if user_id in self.spaetzle_conf()['discord_user_bridge']:
            return self.spaetzle_conf()['discord_user_bridge'][user_id]
        else:
            return None

    def match_status(self, date, time):
        """
        Checks the status of a match (Solely time-based)
        :param date: date of the match ('DD.MM.')
        :param time: time of the kickoff ('HH:MM')
        :return: CLOSED for finished matches, RUNNING for currently active matches (2 hours after kickoff) and UPCOMING
        for matches not started. UNKNOWN if unable to read the date or time
        """
        now = datetime.now()
        try:
            day, month, _ = date.split(".")
            hour, minute = time.split(":")
            year = now.year if int(month) >= 7 else now.year + 1
            match_datetime = datetime(year, int(month), int(day), int(hour), int(minute))
            timedelta = (now - match_datetime).total_seconds()
            if timedelta < 0:
                return MatchStatus.UPCOMING
            elif timedelta < 7200:
                return MatchStatus.RUNNING
            else:
                return MatchStatus.CLOSED
        except ValueError:
            return MatchStatus.UNKNOWN

    def valid_pred(self, pred: Tuple[str, str]):
        return True if pred[0].isnumeric() and pred[1].isnumeric() else False

    def pred_reachable(self, score: Tuple[int, int], pred: Tuple[int, int]):
        return score[0] <= pred[0] and score[1] <= pred[1]

    def points(self, score, pred):
        """
        Returns the points resulting from this score and prediction
        """
        score, pred = (int(score[0]), int(score[1])), (int(pred[0]), int(pred[1]))
        if score == pred:
            return 4
        elif (score[0] - score[1]) == (pred[0] - pred[1]):
            return 3
        elif ((score[0] - score[1]) > 0) - ((score[0] - score[1]) < 0) \
                == ((pred[0] - pred[1]) > 0) - ((pred[0] - pred[1]) < 0):
            return 2
        else:
            return 0

    def pointdiff_possible(self, score, pred1, pred2):
        """
        Returns the maximal point difference possible
        """
        if not self.valid_pred(score):
            # No Score
            if self.valid_pred(pred1) and self.valid_pred(pred2):
                p = 4 - self.points(pred1, pred2)
                diff1, diff2 = p, p
            elif not self.valid_pred(pred1) and not self.valid_pred(pred2):
                diff1, diff2 = 0, 0
            elif not self.valid_pred(pred1):
                diff1, diff2 = 0, 4
            else:
                diff1, diff2 = 4, 0
        else:
            # Running Game
            if not self.valid_pred(pred1) and not self.valid_pred(pred2):
                # Both not existent
                diff1, diff2 = 0, 0
            elif self.valid_pred(pred1) and not self.valid_pred(pred2):
                # No Away
                diff1 = (3 + self.pred_reachable(score, pred1)) - self.points(score, pred1)
                diff2 = self.points(score, pred1)
            elif self.valid_pred(pred2) and not self.valid_pred(pred1):
                # No Home
                diff1 = self.points(score, pred2)
                diff2 = (3 + self.pred_reachable(score, pred2)) - self.points(score, pred2)
            else:
                # Both existent
                if pred1 == pred2:
                    diff1, diff2 = 0, 0
                else:
                    diff1 = (3 + self.pred_reachable(score, pred1) - self.points(pred1, pred2)) \
                            - (self.points(score, pred1) - self.points(score, pred2))
                    diff2 = (3 + self.pred_reachable(score, pred2) - self.points(pred1, pred2)) \
                            - (self.points(score, pred2) - self.points(score, pred1))

        return diff1, diff2

    @commands.group(name="spaetzle", aliases=["spätzle", "spätzles"], invoke_without_command=True,
                    help="commands for managing the 'Spätzles-Tippspiel'")
    async def spaetzle(self, ctx):
        await ctx.send("Keine Spätzles. Nur Fußball :c")

    @spaetzle.command(name="info", help="Get info about the Spaetzles-Tippspiel")
    async def spaetzle_info(self, ctx):
        await ctx.send(self.spaetzle_lang('info'))

    @spaetzle.command(name="link", help="Get the link to the spreadsheet")
    async def spaetzle_doc_link(self, ctx):
        await ctx.send("<https://docs.google.com/spreadsheets/d/{}>".format(self.spaetzle_conf()['spaetzledoc_id']))

    @spaetzle.command(name="user", help="Connects your discord user with a specific spaetzle user")
    async def user_bridge(self, ctx, user=None):
        discord_user = ctx.message.author.id
        # User-Verbindung entfernen
        if user is None:
            if discord_user in self.spaetzle_conf()["discord_user_bridge"]:
                del self.spaetzle_conf()["discord_user_bridge"][discord_user]
                await ctx.message.add_reaction(Lang.CMDSUCCESS)
            else:
                await ctx.send(self.spaetzle_lang('user_not_bridged'))
            return
        # User-Verbindung hinzufügen
        try:
            self.get_user_cell(user)
            self.spaetzle_conf()["discord_user_bridge"][ctx.message.author.id] = user
            Storage().save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        except UserNotFound:
            await ctx.send(self.spaetzle_lang('user_not_found'))

    @spaetzle.command(name="duel", aliases=["duell"], help="Displays the duel of a specific user")
    async def show_duel_single(self, ctx, user=None):
        if user is None:
            user = self.get_bridged_user(ctx.message.author.id)
            if user is None:
                await ctx.send(self.spaetzle_lang('user_not_bridged'))
                return
        c = self.get_api_client()

        try:
            col1, row1 = self.get_user_cell(user)
        except UserNotFound:
            await ctx.send(self.spaetzle_lang('user_not_found'))
            return
        result = c.get("Aktuell!{}:{}".format(c.cellname(col1, row1 + 10), c.cellname(col1 + 1, row1 + 11)))
        opponent = result[1][1]

        # Getting data / Opponent-dependent parts
        try:
            col2, row2 = self.get_user_cell(opponent)
        except UserNotFound:
            # Opponent not found
            oppo_predictions = self.spaetzle_lang('user_not_found')
            matches, preds_h = c.get_multiple([self.spaetzle_conf()['matches_range'],
                                               "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                      c.cellname(col1 + 1, row1 + 9))])
            preds_a = [["–", "–"]]*9
        else:
            # Opponent found
            oppo_predictions = ""
            matches, preds_h, preds_a = c.get_multiple([self.spaetzle_conf()['matches_range'],
                                                        "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                               c.cellname(col1 + 1, row1 + 9)),
                                                        "Aktuell!{}:{}".format(c.cellname(col2, row2 + 1),
                                                                               c.cellname(col2 + 1, row2 + 9))])
        # Fixing stuff
        if len(matches) == 0:
            await ctx.send(self.spaetzle_lang('no_matches'))
            return
        if len(preds_h) == 0:
            preds_h = [["–", "–"]] * 9
        if len(preds_a) == 0:
            preds_a = [["–", "–"]] * 9
        for i in range(len(matches)):
            if len(preds_h[i]) < 2:
                preds_h[i] = ["–", "–"]
            if len(preds_a[i]) < 2:
                preds_a[i] = ["–", "–"]

        # Calculating possible point difference
        diff1, diff2 = 0, 0
        for i in range(len(matches)):
            if self.match_status(matches[i][1], matches[i][2]) == MatchStatus.CLOSED:
                continue
            diff = self.pointdiff_possible(matches[i][4:6], preds_h[i], preds_a[i])
            diff1 += diff[0]
            diff2 += diff[1]

        # Producing the message
        match_str = ""
        for match in matches:
            emoji = self.match_status(match[1], match[2]).value
            match_str += "{} {} {}:{} {}\n".format(emoji, self.convert_team_name(match[3]), match[4], match[5],
                                                   self.convert_team_name(match[6]))

        user_predictions = ""
        for pred in preds_h:
            if len(pred) < 2:
                user_predictions += "-:-\n"
            else:
                user_predictions += "{}:{}\n".format(pred[0], pred[1])

        if oppo_predictions == "":
            for pred in preds_a:
                if len(pred) < 2:
                    oppo_predictions += "-:-\n"
                else:
                    oppo_predictions += "{}:{}\n".format(pred[0], pred[1])

        embed = discord.Embed(title=user)
        embed.description = "{} [{}:{}] {}".format(user, result[0][0], result[1][0], opponent)
        embed.set_footer(text="Noch möglich aufzuholen: {} bzw {} Punkte".format(diff1, diff2))
        embed.add_field(name="Spiele", value=match_str)
        embed.add_field(name=user, value=user_predictions)
        embed.add_field(name=opponent, value=oppo_predictions)

        await ctx.send(embed=embed)

    @spaetzle.command(name="duels", aliases=["duelle"],
                      help="Displays the duels of observed users or the specified league")
    async def show_duels(self, ctx, league: int = None):
        c = self.get_api_client()
        msg = ""

        if league is None:
            # Observed users
            title = "Duelle"
            data_ranges = []
            observed_users = self.spaetzle_conf()['observed_users']

            for user in observed_users:
                try:
                    col, row = self.get_user_cell(user)
                    data_ranges.append("Aktuell!{}".format(c.cellname(col, row)))
                    data_ranges.append("Aktuell!{}:{}".format(c.cellname(col, row + 10), c.cellname(col + 1, row + 11)))
                except UserNotFound:
                    pass
            data = c.get_multiple(data_ranges)
            for i in range(0, len(data_ranges), 2):
                user = data[i][0][0]
                opponent = data[i + 1][1][1]
                if opponent in observed_users:
                    if observed_users.index(opponent) > observed_users.index(user):
                        msg += "**{}** [{}:{}] **{}**\n".format(user, data[i + 1][0][0], data[i + 1][1][0], opponent)
                else:
                    msg += "**{}** [{}:{}] {}\n".format(user, data[i + 1][0][0], data[i + 1][1][0], opponent)
        else:
            # League
            title = "Duelle Liga {}".format(league)
            if league == 1:
                result = c.get("Aktuell!J3:T11")
            elif league == 2:
                result = c.get("Aktuell!V3:AF11")
            elif league == 3:
                result = c.get("Aktuell!AH3:AR11")
            elif league == 4:
                result = c.get("Aktuell!AT3:BD11")
            else:
                await ctx.send(self.spaetzle_lang('invalid_league'))
                return

            for match in result:
                if len(match) >= 8:
                    msg += "{0} [{4}:{5}] {7}\n".format(*match)

        await ctx.send(embed=discord.Embed(title=title, description=msg))

    @spaetzle.command(name="matches", aliases=["spiele"], help="Displays the matches to be predicted")
    async def show_matches(self, ctx):
        c = self.get_api_client()
        matches = c.get(self.spaetzle_conf()['matches_range'])

        if len(matches) == 0:
            await ctx.send(self.spaetzle_lang('no_matches'))
            return

        msg = ""
        for match in matches:
            emoji = self.match_status(match[1], match[2]).value
            msg += "{0} {1} {2} {3} Uhr | {4} - {7} | {5}:{6}\n".format(emoji, *match)

        await ctx.send(embed=discord.Embed(title="Spiele", description=msg))

    @spaetzle.command(name="table", aliases=["tabelle", "league", "liga"],
                      help="Displays the table of a specific league")
    async def show_table(self, ctx, user_or_league=None):
        c = self.get_api_client()

        if user_or_league is None:
            user_or_league = self.get_bridged_user(ctx.message.author.id)
            if user_or_league is None:
                await ctx.send(self.spaetzle_lang('user_not_bridged'))
                return

        try:
            # League
            league = int(user_or_league)
        except ValueError:
            # User
            try:
                league = self.get_user_league(user_or_league)
            except UserNotFound:
                ctx.send(self.spaetzle_lang('user_not_found'))
                return

        if league == 1:
            result = c.get("Aktuell!J14:T31")
        elif league == 2:
            result = c.get("Aktuell!V14:AF31")
        elif league == 3:
            result = c.get("Aktuell!AH14:AR31")
        elif league == 4:
            result = c.get("Aktuell!AT14:BD31")
        else:
            await ctx.send(self.spaetzle_lang('invalid_league'))
            return

        if isinstance(user_or_league, str):
            # Restrict the view to users area
            pos = None
            for i in range(len(result)):
                pos = i if result[i][3] == user_or_league else pos
            if pos is not None:
                result = result[max(0, pos - 3):pos + 4]

        msg = ""
        for line in result:
            msg += "{0}{1} | {4} | {7}:{9} {10} | {11}{0}\n".format("**" if line[3] == user_or_league else "", *line)

        await ctx.send(embed=discord.Embed(title="Tabelle Liga {}".format(league), description=msg))

    @spaetzle.group(name="observe", invoke_without_command=True,
                    help="Configure which users should be observed.")
    async def observe(self, ctx):
        await ctx.invoke(self.bot.get_command('spaetzle observe list'))

    @observe.command(name="list", help="Lists the observed users")
    async def observe_list(self, ctx):
        await ctx.send(", ".join(self.spaetzle_conf()['observed_users']))

    @observe.command(name="add", help="Adds a user to be observed")
    async def observe_add(self, ctx, user):
        try:
            self.get_user_league(user)
        except UserNotFound:
            await ctx.send(self.spaetzle_lang('user_not_found'))
            return

        if user not in self.spaetzle_conf()['observed_users']:
            self.spaetzle_conf()['observed_users'].append(user)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @observe.command(name="remove", help="Removes a user from the observation")
    async def observe_remove(self, ctx, user):
        if user in self.spaetzle_conf()['observed_users']:
            self.spaetzle_conf()['observed_users'].remove(user)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        else:
            await ctx.send(self.spaetzle_lang('user_not_found'))
