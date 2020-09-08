import calendar
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Tuple

import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient, restclient
from conf import Storage, Lang


class UserNotFound(Exception):
    pass


class LeagueNotFound(Exception):
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
        self.logger = logging.getLogger(__name__)
        self.matches = []
        self.matches_by_team = {}
        self.teamname_dict = self.build_teamname_dict()
        self.get_matches_from_sheets()

    def default_storage(self):
        return {
            'matches_range': "Aktuell!B3:H11",
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8",
            'discord_user_bridge': {},
            'observed_users': [],
            'participants': {
                'liga1': ["TN 1", "TN 2", "TN 3", "TN 4", "TN 5", "TN 6",
                          "TN 7", "TN 8", "TN 9", "TN 10", "TN 11", "TN 12",
                          "TN 13", "TN 14", "TN 15", "TN 16", "TN 17", "TN 18"],
                'liga2': ["TN 19", "TN 20", "TN 21", "TN 22", "TN 23", "TN 24",
                          "TN 25", "TN 26", "TN 27", "TN 28", "TN 29", "TN 30",
                          "TN 31", "TN 32", "TN 33", "TN 34", "TN 35", "TN 36"],
                'liga3': ["TN 37", "TN 38", "TN 39", "TN 40", "TN 41", "TN 42",
                          "TN 43", "TN 44", "TN 45", "TN 46", "TN 47", "TN 48",
                          "TN 49", "TN 50", "TN 51", "TN 52", "TN 53", "TN 54"],
                'liga4': ["TN 55", "TN 56", "TN 57", "TN 58", "TN 59", "TN 60",
                          "TN 61", "TN 62", "TN 63", "TN 64", "TN 65", "TN 66",
                          "TN 67", "TN 68", "TN 69", "TN 70", "TN 71", "TN 72"],
            },
            'teamnames': [
                {'short_name': "FCB", 'long_name': "FC Bayern München", 'other': ["FC Bayern", "Bayern", "München"]},
                {'short_name': "BVB", 'long_name': "Borussia Dortmund", 'other': ["Dortmund"]},
                {'short_name': "LPZ", 'long_name': "Rasenballsport Leipzig",
                 'other': ["Leipzig", "RB Leipzig", "RBL", "LEI"]},
                {'short_name': "BMG", 'long_name': "Bor. Mönchengladbach",
                 'other': ["Gladbach", "Borussia Mönchengladbach"]},
                {'short_name': "LEV", 'long_name': "Bayer 04 Leverkusen",
                 'other': ["Leverkusen", "Bayer Leverkusen", "B04"]},
                {'short_name': "HOF", 'long_name': "TSG Hoffenheim",
                 'other': ["Hoffenheim", "TSG 1899 Hoffenheim", "TSG"]},
                {'short_name': "WOB", 'long_name': "VfL Wolfsburg", 'other': ["Wolfsburg", "VFL"]},
                {'short_name': "SCF", 'long_name': "SC Freiburg", 'other': ["Freiburg"]},
                {'short_name': "SGE", 'long_name': "Eintracht Frankfurt", 'other': ["Frankfurt", "Eintracht", "FRA"]},
                {'short_name': "BSC", 'long_name': "Hertha BSC", 'other': ["Hertha"]},
                {'short_name': "FCU", 'long_name': "1. FC Union Berlin", 'other': ["Union", "Berlin"]},
                {'short_name': "S04", 'long_name': "FC Schalke 04", 'other': ["Schalke"]},
                {'short_name': "M05", 'long_name': "1. FSV Mainz 05", 'other': ["Mainz", "FSV"]},
                {'short_name': "KOE", 'long_name': "1. FC Köln", 'other': ["Köln", "FCK"]},
                {'short_name': "FCA", 'long_name': "FC Augsburg", 'other': ["Augsburg"]},
                {'short_name': "SVW", 'long_name': "SV Werder Bremen",
                 'other': ["Bremen", "Werder", "Werder Bremen", "BRE"]},
                {'short_name': "DSC", 'long_name': "Arminia Bielefeld", 'other': ["Bielefeld", "Arminia", "BIE"]},
                {'short_name': "VFB", 'long_name': "VfB Stuttgart", 'other': ["Stuttgart", "STU"]}
            ]
        }

    def spaetzle_conf(self):
        return Storage().get(self)

    def get_api_client(self):
        return sheetsclient.Client(self.spaetzle_conf()['spaetzledoc_id'])

    def is_teamname_abbr(self, team):
        return team is not None and len(team) <= 3

    def build_teamname_dict(self):
        teamdict = {}
        teamnames = self.spaetzle_conf()['teamnames']
        for team in teamnames:
            teamdict[team['short_name']] = team['long_name']
            teamdict[team['long_name']] = team['short_name']
        for team in teamnames:
            for name in team['other']:
                if self.is_teamname_abbr(name):
                    # Abbreviation
                    result = teamdict.setdefault(name, team['long_name'])
                    if result is not team['long_name']:
                        self.logger.debug("{} is already noted with the name {}".format(name, result))
                else:
                    # Long name
                    result = teamdict.setdefault(name, team['short_name'])
                    if result is not team['short_name']:
                        self.logger.debug("{} is already noted with the abbreviation {}".format(name, result))
        return teamdict

    def get_schedule(self, league: int, matchday: int):
        matchday = [5, 16, 15, 1, 12, 9, 8, 4, 13, 10, 11, 7, 14, 3, 6, 0, 2][matchday-1]  # "Randomize" input
        participants = self.spaetzle_conf()['participants'].get('liga{}'.format(league))
        if participants is None:
            raise LeagueNotFound()
        participants = participants[0:1] + participants[matchday-1:] + participants[1:matchday-1]
        schedule = [
            (participants[0], participants[1]),
            (participants[2], participants[17]),
            (participants[3], participants[16]),
            (participants[4], participants[15]),
            (participants[5], participants[14]),
            (participants[6], participants[13]),
            (participants[7], participants[12]),
            (participants[8], participants[11]),
            (participants[9], participants[10])
        ]
        return schedule

    def get_schedule_opponent(self, participant, matchday: int):
        league = self.get_user_league(participant)
        schedule = self.get_schedule(league, matchday)
        for home, away in schedule:
            if home == participant:
                return away
            if away == participant:
                return home
        else:
            return None

    def get_teamname_long(self, team):
        name = self.teamname_dict.get(team)
        if self.is_teamname_abbr(name):
            name = self.teamname_dict.get(name)
        return name

    def get_teamname_abbr(self, team):
        name = self.teamname_dict.get(team)
        if not self.is_teamname_abbr(name):
            name = self.teamname_dict.get(name)
        return name

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

    def get_bridged_user(self, user_id):
        """
        Bridge between a Discord user and a Spätzle participant
        """
        if user_id in self.spaetzle_conf()['discord_user_bridge']:
            return self.spaetzle_conf()['discord_user_bridge'][user_id]
        else:
            return None

    def match_status(self, match_datetime: datetime):
        """
        Checks the status of a match (Solely time-based)

        :param match_datetime: datetime of kick-off
        :return: CLOSED for finished matches, RUNNING for currently active matches (2 hours after kickoff) and UPCOMING
        for matches not started. UNKNOWN if unable to read the date or time
        """
        now = datetime.now()
        try:
            timediff = (now - match_datetime).total_seconds()
            if timediff < 0:
                return MatchStatus.UPCOMING
            elif timediff < 7200:
                return MatchStatus.RUNNING
            else:
                return MatchStatus.CLOSED
        except ValueError:
            return MatchStatus.UNKNOWN

    def valid_pred(self, pred: tuple):
        try:
            int(pred[0]), int(pred[1])
        except ValueError:
            return False
        else:
            return True

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

    @commands.command(name="goal", help="Scores a goal for a team")
    async def goal(self, ctx, team, goals: int = None):
        abbr = self.get_teamname_abbr(team)
        if abbr is not None:
            match = self.matches_by_team[abbr]
            match[abbr]['goals'] = goals if goals is not None else match[abbr]['goals'] + 1
            title = "{0} [{1}:{3}] {2}".format(match['team_home'], match[self.get_teamname_abbr(match['team_home'])],
                                               match['team_away'], match[self.get_teamname_abbr(match['team_away'])])
            embed = discord.Embed(title=title, description="Hier kommen die veränderten Duellstände hin")
            await ctx.send(Lang.lang(self, "goal_scored", team), embed=embed)

    @commands.group(name="spaetzle", aliases=["spätzle", "spätzles"],
                    help="commands for managing the 'Spätzles-Tippspiel'")
    async def spaetzle(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Keine Spätzles. Nur Fußball :c")

    @spaetzle.command(name="info", help="Get info about the Spaetzles-Tippspiel")
    async def spaetzle_info(self, ctx):
        await ctx.send(Lang.lang(self, 'info'))

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
                Storage().save(self)
                await ctx.message.add_reaction(Lang.CMDSUCCESS)
            else:
                await ctx.send(Lang.lang(self, 'user_not_bridged'))
            return
        # User-Verbindung hinzufügen
        try:
            self.get_user_cell(user)
            self.spaetzle_conf()["discord_user_bridge"][ctx.message.author.id] = user
            Storage().save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        except UserNotFound:
            await ctx.send(Lang.lang(self, 'user_not_found'))

    @spaetzle.group(name="set", help="Set data about next matchday etc")
    async def spaetzle_set(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.spaetzle_set)

    @spaetzle_set.command(name="matches", aliases=["spiele"])
    async def set_matches(self, ctx, matchday: int = None):
        async with ctx.typing():
            # Request data
            if matchday is None:
                match_list = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/bl1")
                try:
                    matchday = match_list[0].get('Group', {}).get('GroupOrderID', 0)
                except IndexError:
                    await ctx.message.add_reaction(Lang.CMDERROR)
                    return
                for match in match_list:
                    if match.get('MatchIsFinished', True) is False:
                        break
                else:
                    matchday += 1
                    match_list = restclient.Client("https://www.openligadb.de/api").make_request(
                        "/getmatchdata/bl1/2020/{}".format(str(matchday)))
            else:
                match_list = restclient.Client("https://www.openligadb.de/api").make_request(
                    "/getmatchdata/bl1/2020/{}".format(str(matchday)))

            # Extract matches
            self.matches.clear()
            for i in range(len(match_list)):
                match = match_list[i]
                home = self.get_teamname_abbr(match.get('Team1', {}).get('TeamName', 'n.a.'))
                away = self.get_teamname_abbr(match.get('Team2', {}).get('TeamName', 'n.a.'))
                match_dict = {
                    'match_date_time': datetime.strptime(match.get('MatchDateTime', '0001-01-01T01:01:01'),
                                                         "%Y-%m-%dT%H:%M:%S"),
                    'team_home': self.get_teamname_long(home),
                    'team_away': self.get_teamname_long(away),
                    home: {
                        'cell': (4, i),
                        'goals': 0
                    },
                    away: {
                        'cell': (5, i),
                        'goals': 0
                    },
                }
                self.matches.append(match_dict)
                self.matches_by_team[home] = match_dict
                self.matches_by_team[away] = match_dict

            # Put matches into spreadsheet
            c = self.get_api_client()
            values = []
            for match in self.matches:
                date_time = match.get('match_date_time')
                values.append([calendar.day_abbr[date_time.weekday()],
                               date_time.strftime("%d.%m.%Y"), date_time.strftime("%H:%M"),
                               match.get('team_home'), "–", "–", match.get('team_away')])
            c.update(self.spaetzle_conf()['matches_range'], values, raw=False)

            msg = ""
            for row in values:
                msg += "{0} {1} {2} Uhr | {3} - {6}\n".format(*row)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await ctx.send(embed=discord.Embed(title="Spieltag {}".format(matchday), description=msg))

    @spaetzle_set.command(name="duels", aliases=["duelle"])
    async def set_duels(self, ctx, matchday: int, league: int = None):
        if matchday < 1 or matchday > 17:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'matchday_out_of_range'))

        if league is None:
            schedules = (self.get_schedule(1, matchday), self.get_schedule(2, matchday),
                         self.get_schedule(3, matchday), self.get_schedule(4, matchday))
            embed = discord.Embed(title="Spieltag {} - Duelle".format(matchday))
            for i in range(len(schedules)):
                msg = ""
                for duel in schedules[i]:
                    msg += "{} - {}\n".format(*duel)
                embed.add_field(name="Liga {}".format(i+1), value=msg)
            await ctx.send(embed=embed)
        else:
            schedule = self.get_schedule(league, matchday)
            msg = ""
            for duel in schedule:
                msg += "{} - {}\n".format(*duel)
            await ctx.send(embed=discord.Embed(title="Liga {} - Spieltag {}".format(league, matchday), description=msg))
        # TODO confirm before setting
        # TODO put duels really into the spreadsheet

    def get_matches_from_sheets(self):
        """
        Reads the matches from the sheet
        """
        c = self.get_api_client()
        matches = c.get(self.spaetzle_conf()['matches_range'], formatted=False)

        # Extract matches
        self.matches.clear()
        for i in range(len(matches)):
            match = matches[i]
            home = self.get_teamname_abbr(match[3])
            away = self.get_teamname_abbr(match[6])
            match_dict = {
                'match_date_time': datetime(1899, 12, 30) + timedelta(days=match[1] + match[2]),
                'team_home': self.get_teamname_long(home),
                'team_away': self.get_teamname_long(away),
                home: {
                    'cell': (4, i),
                    'goals': match[4] if isinstance(match[4], int) else 0
                },
                away: {
                    'cell': (5, i),
                    'goals': match[5] if isinstance(match[5], int) else 0
                },
            }
            self.matches.append(match_dict)
            self.matches_by_team[home] = match_dict
            self.matches_by_team[away] = match_dict

    @spaetzle.command(name="duel", aliases=["duell"], help="Displays the duel of a specific user")
    async def show_duel_single(self, ctx, user=None):
        async with ctx.typing():
            if user is None:
                user = self.get_bridged_user(ctx.message.author.id)
                if user is None:
                    await ctx.send(Lang.lang(self, 'user_not_bridged'))
                    return
            c = self.get_api_client()

            try:
                col1, row1 = self.get_user_cell(user)
            except UserNotFound:
                await ctx.send(Lang.lang(self, 'user_not_found'))
                return
            result = c.get("Aktuell!{}:{}".format(c.cellname(col1, row1 + 10), c.cellname(col1 + 1, row1 + 11)))
            opponent = result[1][1]

            # Getting data / Opponent-dependent parts
            try:
                col2, row2 = self.get_user_cell(opponent)
            except UserNotFound:
                # Opponent not found
                oppo_predictions = Lang.lang(self, 'user_not_found')
                matches, preds_h = c.get_multiple([self.spaetzle_conf()['matches_range'],
                                                   "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                          c.cellname(col1 + 1, row1 + 9))],
                                                  formatted=False)
                preds_a = [["–", "–"]] * 9
            else:
                # Opponent found
                oppo_predictions = ""
                matches, preds_h, preds_a = c.get_multiple([self.spaetzle_conf()['matches_range'],
                                                            "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                                   c.cellname(col1 + 1, row1 + 9)),
                                                            "Aktuell!{}:{}".format(c.cellname(col2, row2 + 1),
                                                                                   c.cellname(col2 + 1, row2 + 9))],
                                                           formatted=False)
            # Fixing stuff
            if len(matches) == 0:
                await ctx.send(Lang.lang(self, 'no_matches'))
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
                if self.match_status(datetime(1899, 12, 30)
                                     + timedelta(days=matches[i][1] + matches[i][2])) == MatchStatus.CLOSED:
                    continue
                diff = self.pointdiff_possible(matches[i][4:6], preds_h[i], preds_a[i])
                diff1 += diff[0]
                diff2 += diff[1]

            # Producing the message
            match_str = ""
            for match in matches:
                emoji = self.match_status(datetime(1899, 12, 30) + timedelta(days=match[1] + match[2])).value
                match_str += "{} {} {}:{} {}\n".format(emoji, self.get_teamname_abbr(match[3]), match[4], match[5],
                                                       self.get_teamname_abbr(match[6]))

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
        async with ctx.typing():
            c = self.get_api_client()
            msg = ""

            if league is None:
                # Observed users
                title = "Duelle"
                data_ranges = []
                observed_users = self.spaetzle_conf()['observed_users']

                if len(observed_users) == 0:
                    msg = Lang.lang(self, 'no_observed_users')
                else:
                    for user in observed_users:
                        try:
                            col, row = self.get_user_cell(user)
                            data_ranges.append("Aktuell!{}".format(c.cellname(col, row)))
                            data_ranges.append(
                                "Aktuell!{}:{}".format(c.cellname(col, row + 10), c.cellname(col + 1, row + 11)))
                        except UserNotFound:
                            pass
                    data = c.get_multiple(data_ranges)
                    for i in range(0, len(data_ranges), 2):
                        user = data[i][0][0]
                        opponent = data[i + 1][1][1]
                        if opponent in observed_users:
                            if observed_users.index(opponent) > observed_users.index(user):
                                msg += "**{}** [{}:{}] **{}**\n".format(user, data[i + 1][0][0], data[i + 1][1][0],
                                                                        opponent)
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
                    await ctx.send(Lang.lang(self, 'invalid_league'))
                    return

                for match in result:
                    if len(match) >= 8:
                        msg += "{0} [{4}:{5}] {7}\n".format(*match)

            await ctx.send(embed=discord.Embed(title=title, description=msg))

    @spaetzle.command(name="matches", aliases=["spiele"], help="Displays the matches to be predicted")
    async def show_matches(self, ctx):
        async with ctx.typing():
            c = self.get_api_client()
            matches = c.get(self.spaetzle_conf()['matches_range'], formatted=False)

            if len(matches) == 0:
                await ctx.send(Lang.lang(self, 'no_matches'))
                return

            msg = ""
            for match in matches:
                date_time = datetime(1899, 12, 30) + timedelta(days=match[1] + match[2])
                emoji = self.match_status(date_time).value
                msg += "{0} {3} {1} {2} Uhr | {6} - {9} | {7}:{8}\n".format(emoji, date_time.strftime("%d.%m."),
                                                                            date_time.strftime("%H:%M"), *match)
            await ctx.send(embed=discord.Embed(title="Spiele", description=msg))

    @spaetzle.command(name="table", aliases=["tabelle", "league", "liga"],
                      help="Displays the table of a specific league")
    async def show_table(self, ctx, user_or_league=None):
        async with ctx.typing():
            c = self.get_api_client()

            if user_or_league is None:
                user_or_league = self.get_bridged_user(ctx.message.author.id)
                if user_or_league is None:
                    await ctx.send(Lang.lang(self, 'user_not_bridged'))
                    return

            try:
                # League
                league = int(user_or_league)
            except ValueError:
                # User
                try:
                    league = self.get_user_league(user_or_league)
                except UserNotFound:
                    ctx.send(Lang.lang(self, 'user_not_found'))
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
                await ctx.send(Lang.lang(self, 'invalid_league'))
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
                msg += "{0}{1} | {4} | {7}:{9} {10} | {11}{0}\n".format("**" if line[3] == user_or_league else "",
                                                                        *line)

            await ctx.send(embed=discord.Embed(title="Tabelle Liga {}".format(league), description=msg))

    @spaetzle.command(name="fixtures", help="Lists fixtures for a specific participant")
    async def show_fixtures(self, ctx, user=None):
        if user is None:
            user = self.get_bridged_user(ctx.message.author.id)
            if user is None:
                await ctx.send(Lang.lang(self, 'user_not_bridged'))
                return

        msg = ""
        for i in range(1, 18):
            msg += "{} | {}\n".format(i, self.get_schedule_opponent(user, i))

        await ctx.send(embed=discord.Embed(title="Gegner von {}".format(user), description=msg))

    @spaetzle.group(name="observe",
                    help="Configure which users should be observed.")
    async def observe(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle observe list'))

    @observe.command(name="list", help="Lists the observed users")
    async def observe_list(self, ctx):
        if len(self.spaetzle_conf()['observed_users']) == 0:
            msg = Lang.lang(self, 'no_observed_users')
        else:
            msg = ", ".join(self.spaetzle_conf()['observed_users'])
        await ctx.send(msg)

    @observe.command(name="add", help="Adds a user to be observed")
    async def observe_add(self, ctx, user):
        try:
            self.get_user_league(user)
        except UserNotFound:
            await ctx.send(Lang.lang(self, 'user_not_found'))
            return

        if user not in self.spaetzle_conf()['observed_users']:
            self.spaetzle_conf()['observed_users'].append(user)
            Storage().save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @observe.command(name="del", help="Removes a user from the observation")
    async def observe_remove(self, ctx, user):
        if user in self.spaetzle_conf()['observed_users']:
            self.spaetzle_conf()['observed_users'].remove(user)
            Storage().save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        else:
            await ctx.send(Lang.lang(self, 'user_not_found'))

    @spaetzle.command(name="selfmatches")
    async def monitoring_matches(self, ctx):
        if len(self.matches) == 0:
            await ctx.send(Lang.lang(self, 'no_matches'))
            return

        msg = ""
        for match in self.matches:
            date_time = match.get('match_date_time')
            home = match.get('team_home')
            away = match.get('team_away')
            msg += "{} {} {} Uhr | {} - {} | {}:{}\n".format(calendar.day_abbr[date_time.weekday()],
                                                             date_time.strftime("%d.%m."), date_time.strftime("%H:%M"),
                                                             home, away,
                                                             match.get(self.get_teamname_abbr(home)).get('goals'),
                                                             match.get(self.get_teamname_abbr(away)).get('goals'))
        await ctx.send(embed=discord.Embed(title="self.matches", description=msg))