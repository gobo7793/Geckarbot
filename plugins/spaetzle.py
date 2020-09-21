import calendar
import logging
import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Tuple
from urllib.parse import urljoin, urlparse

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient, restclient
from botutils.converters import get_best_username
from botutils.permchecks import check_full_access
from botutils.stringutils import paginate
from botutils.utils import add_reaction
from conf import Config, Storage, Lang


class UserNotFound(Exception):
    pass


class LeagueNotFound(Exception):
    pass


class MatchStatus(Enum):
    CLOSED = "💤"
    RUNNING = "🟩"
    UPCOMING = "🕓"
    UNKNOWN = "❔"


class MatchResult(Enum):
    HOME = -1
    DRAW = 0
    AWAY = 1
    NONE = None


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

    def default_config(self):
        return {
            'manager': 0,
            'trusted': [],
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8",
            'matches_range': "B1:H11",
            'duel_ranges': {
                1: "J3:T11",
                2: "V3:AF11",
                3: "AH3:AR11",
                4: "AT3:BD11"
            },
            'table_ranges': {
                1: "J14:T31",
                2: "V14:AF31",
                3: "AH14:AR31",
                4: "AT14:BD31"
            },
            'predictions_range': "BH2:CQ49",
            'user_agent': "{'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, "
                          "like Gecko) Chrome/56.0.2924.87 Safari/537.36',} "
        }

    def default_storage(self):
        return {
            'matchday': 0,
            'main_thread': None,
            'predictions_thread': None,
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
            'teamnames': {
                "FC Bayern München": {'short_name': "FCB", 'other': ["FC Bayern", "Bayern", "München"]},
                "Borussia Dortmund": {'short_name': "BVB", 'other': ["Dortmund"]},
                "Rasenballsport Leipzig": {'short_name': "LPZ", 'other': ["Leipzig", "RB Leipzig", "RBL", "LEI"]},
                "Bor. Mönchengladbach": {'short_name': "BMG", 'other': ["Gladbach", "Borussia Mönchengladbach"]},
                "Bayer 04 Leverkusen": {'short_name': "LEV", 'other': ["Leverkusen", "Bayer Leverkusen", "B04"]},
                "TSG Hoffenheim": {'short_name': "HOF", 'other': ["Hoffenheim", "TSG 1899 Hoffenheim", "TSG"]},
                "VfL Wolfsburg": {'short_name': "WOB", 'other': ["Wolfsburg", "VFL"]},
                "SC Freiburg": {'short_name': "SCF", 'other': ["Freiburg"]},
                "Eintracht Frankfurt": {'short_name': "SGE", 'other': ["Frankfurt", "Eintracht", "FRA"]},
                "Hertha BSC": {'short_name': "BSC", 'other': ["Hertha"]},
                "1. FC Union Berlin": {'short_name': "FCU", 'other': ["Union", "Berlin"]},
                "FC Schalke 04": {'short_name': "S04", 'other': ["Schalke"]},
                "1. FSV Mainz 05": {'short_name': "M05", 'other': ["Mainz", "FSV"]},
                "1. FC Köln": {'short_name': "KOE", 'other': ["Köln", "FCK"]},
                "FC Augsburg": {'short_name': "FCA", 'other': ["Augsburg"]},
                "SV Werder Bremen": {'short_name': "SVW", 'other': ["Bremen", "Werder", "Werder Bremen", "BRE"]},
                "Arminia Bielefeld": {'short_name': "DSC", 'other': ["Bielefeld", "Arminia", "BIE"]},
                "VfB Stuttgart": {'short_name': "VFB", 'other': ["Stuttgart", "STU"]}
            },
            'predictions': []
        }

    def get_api_client(self):
        return sheetsclient.Client(Config().get(self)['spaetzledoc_id'])

    async def manager_check(self, ctx, show_error=True):
        if ctx.author.id == Config().get(self)['manager']:
            return True
        else:
            if show_error:
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                await ctx.send(Lang.lang(self, 'manager_only'))
            return False

    async def trusted_check(self, ctx, show_error=True):
        if ctx.message.author.id in Config.get(self)['trusted'] or ctx.message.author.id == Config.get(self)['manager']:
            return True
        else:
            if show_error:
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                await ctx.send(Lang.lang(self, 'not_trusted'))
            return False

    def is_teamname_abbr(self, team):
        return team is not None and len(team) <= 3

    def build_teamname_dict(self):
        teamdict = {}
        teamnames = Storage().get(self)['teamnames']
        for long_name, team in teamnames.items():
            teamdict[team['short_name']] = long_name
            teamdict[long_name] = team['short_name']
        for long_name, team in teamnames.items():
            for name in team['other']:
                if self.is_teamname_abbr(name):
                    # Abbreviation
                    result = teamdict.setdefault(name, long_name)
                    if result is not long_name:
                        self.logger.debug("{} is already noted with the name {}".format(name, result))
                else:
                    # Long name
                    result = teamdict.setdefault(name, team['short_name'])
                    if result is not team['short_name']:
                        self.logger.debug("{} is already noted with the abbreviation {}".format(name, result))
        return teamdict

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

    def get_schedule(self, league: int, matchday: int):
        matchday = [5, 16, 15, 1, 12, 9, 8, 4, 13, 10, 11, 7, 14, 3, 6, 0, 2][matchday - 1]  # "Randomize" input
        p = Storage().get(self)['participants'].get('liga{}'.format(league))
        participants = [p[i] for i in [11, 0, 13, 6, 5, 15, 9, 1, 14, 8, 4, 16, 7, 2, 17, 3, 10, 12]]
        if participants is None:
            raise LeagueNotFound()
        participants = participants[0:1] + participants[matchday - 1:] + participants[1:matchday - 1]
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

    def get_user_cell(self, user):
        """
        Returns the position of the user's title cell in the 'Tipps' section

        :return: (col, row) of the cell
        """
        participants = Storage().get(self)['participants']
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
        participants = Storage().get(self)['participants']
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
        if user_id in Storage().get(self)['discord_user_bridge']:
            return Storage().get(self)['discord_user_bridge'][user_id]
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
        Returns the maximal point difference possible at a single match
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

    def determine_winner(self, points_h: str, points_a: str, diff_h: int, diff_a: int):
        """
        Determines the winner of a duel
        :param points_h: current points of user 1
        :param points_a: current points of user 2
        :param diff_h: maximum points user 1 can catch up
        :param diff_a: maximum points user 2 can catch up
        :return: MatchResult
        """
        try:
            points_h = int(points_h)
        except (ValueError, TypeError):
            points_h = 0
        try:
            points_a = int(points_a)
        except (ValueError, TypeError):
            points_a = 0

        if points_h > (points_a + diff_a):
            return MatchResult.HOME
        elif points_a > (points_h + diff_h):
            return MatchResult.AWAY
        elif points_h == points_a and diff_h == 0 and diff_a == 0:
            return MatchResult.DRAW
        else:
            return MatchResult.NONE

    @commands.command(name="goal", help="Scores a goal for a team (Spätzle-command)")
    async def goal(self, ctx, team, goals: int = None):
        abbr = self.get_teamname_abbr(team)
        if abbr is None:
            await ctx.send(Lang.lang(self, 'team_not_found', team))
        else:
            async with ctx.typing():
                c = self.get_api_client()
                match = self.matches_by_team[abbr]
                if self.match_status(match['match_date_time']) == MatchStatus.UPCOMING:
                    await ctx.send(Lang.lang(self, 'match_is_in_future'))
                    return
                match[abbr]['goals'] = goals if goals is not None else match[abbr]['goals'] + 1

                if abbr == self.get_teamname_abbr(match['team_home']):
                    msg = "{0} [**{1}**:{3}] {2}"
                else:
                    msg = "{0} [{1}:**{3}**] {2}"
                msg = msg.format(match['team_home'], match[self.get_teamname_abbr(match['team_home'])]['goals'],
                                 match['team_away'], match[self.get_teamname_abbr(match['team_away'])]['goals'])
                await ctx.send(msg)

                data = [x[:] for x in [[None] * 7] * 11]
                cell_x, cell_y = match[abbr]['cell']
                data[cell_y] = data[cell_y].copy()
                data[cell_y][cell_x] = match[abbr]['goals']
                c.update(Config().get(self)['matches_range'], data)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.group(name="spaetzle", aliases=["spätzle", "spätzles"],
                    help="commands for managing the 'Spätzles-Tippspiel'")
    async def spaetzle(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle info'))

    @spaetzle.command(name="info", help="Get info about the Spaetzles-Tippspiel")
    async def spaetzle_info(self, ctx):
        embed = discord.Embed(title="Spätzle(s)-Tippspiel", description=Lang.lang(self, 'info'))
        embed.add_field(name=Lang.lang(self, 'title_spreadsheet'), value="<https://docs.google.com/spreadsheets/d/{}>"
                        .format(Config().get(self)['spaetzledoc_id']), inline=False)
        embed.add_field(name=Lang.lang(self, 'title_main_thread'), value=Storage().get(self)['main_thread'])
        embed.add_field(name=Lang.lang(self, 'title_predictions_thread'),
                        value=Storage().get(self)['predictions_thread'])
        await ctx.send(embed=embed)

    @spaetzle.command(name="link", help="Get the link to the spreadsheet")
    async def spaetzle_doc_link(self, ctx):
        await ctx.send("<https://docs.google.com/spreadsheets/d/{}>".format(Config().get(self)['spaetzledoc_id']))

    @spaetzle.command(name="user", help="Connects your discord user with a specific spaetzle user")
    async def user_bridge(self, ctx, user=None):
        discord_user = ctx.message.author.id
        # User-Verbindung entfernen
        if user is None:
            if discord_user in Storage().get(self)["discord_user_bridge"]:
                del Storage().get(self)["discord_user_bridge"][discord_user]
                Storage().save(self)
                await add_reaction(ctx.message, Lang.CMDSUCCESS)
            else:
                await ctx.send(Lang.lang(self, 'user_not_bridged'))
            return
        # User-Verbindung hinzufügen
        try:
            self.get_user_cell(user)
            Storage().get(self)["discord_user_bridge"][ctx.message.author.id] = user
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        except UserNotFound:
            await ctx.send(Lang.lang(self, 'user_not_found'))

    @spaetzle.group(name="set", help="Set data about next matchday etc")
    async def spaetzle_set(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.spaetzle_set)

    @spaetzle_set.command(name="matches", aliases=["spiele"])
    async def set_matches(self, ctx, matchday: int = None):
        if not await self.trusted_check(ctx):
            return
        async with ctx.typing():
            # Request data
            if matchday is None:
                match_list = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/bl1")
                try:
                    matchday = match_list[0].get('Group', {}).get('GroupOrderID', 0)
                except IndexError:
                    await add_reaction(ctx.message, Lang.CMDERROR)
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
                        'cell': (4, i+2),
                        'goals': 0
                    },
                    away: {
                        'cell': (5, i+2),
                        'goals': 0
                    },
                }
                self.matches.append(match_dict)
                self.matches_by_team[home] = match_dict
                self.matches_by_team[away] = match_dict

            # Put matches into spreadsheet
            c = self.get_api_client()
            values = [[matchday], [None]]
            for match in self.matches:
                date_time = match.get('match_date_time')
                date_formula = '=IF(DATE({};{};{}) + TIME({};{};0) < F12;0;"")'.format(*list(date_time.timetuple()))
                values.append([calendar.day_abbr[date_time.weekday()],
                               date_time.strftime("%d.%m.%Y"), date_time.strftime("%H:%M"),
                               match.get('team_home'), date_formula, date_formula, match.get('team_away')])
            c.update("Aktuell!{}".format(Config().get(self)['matches_range']), values, raw=False)

            # Set matchday
            Storage().get(self)['matchday'] = matchday
            Storage().save(self)

            msg = ""
            for row in values[2:]:
                msg += "{0} {1} {2} Uhr | {3} - {6}\n".format(*row)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send(embed=discord.Embed(title="Spieltag {}".format(matchday), description=msg))

    @spaetzle_set.command(name="duels", aliases=["duelle"])
    async def set_duels(self, ctx, matchday: int, league: int = None):
        if not await self.trusted_check(ctx):
            return
        if matchday not in range(1, 18):
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'matchday_out_of_range'))
        if league is not None and league not in range(1, 5):
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_league'))

        async with ctx.typing():
            c = self.get_api_client()
            embed = discord.Embed()
            if league is None:
                schedules = {
                    1: self.get_schedule(1, matchday),
                    2: self.get_schedule(2, matchday),
                    3: self.get_schedule(3, matchday),
                    4: self.get_schedule(4, matchday)
                }
                embed.title = "Spieltag {} - Duelle".format(matchday)
            else:
                schedules = {
                    league: self.get_schedule(league, matchday)
                }
                embed.title = "Spieltag {} - Duelle Liga {}".format(matchday, league)

            data = {}
            for leag, duels in schedules.items():
                msg = ""
                data[leag] = []
                for duel in duels:
                    msg += "{} - {}\n".format(*duel)
                    data[leag].append([duel[0], None, None, None, None, None, None, duel[1]])
                if len(schedules) > 1:
                    embed.add_field(name="Liga {}".format(leag), value=msg)
                else:
                    embed.description = msg
            message = await ctx.send(embed=embed)

            # FIXME replace with update_multiple once its working fine
            if league is None:
                combined_data = [x[:] for x in [[]]*9]
                for values in data.values():
                    for i in range(len(values)):
                        combined_data[i].extend(values[i] + [None] * 4)
                c.update("Aktuell!J3:BD11", combined_data)
            else:
                c.update(Config().get(self)['duel_ranges'].get(league), data.get(league))
        await add_reaction(message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="scrape", help="Scrapes the predictions thread for forum posts")
    async def set_scrape(self, ctx):
        if not await self.trusted_check(ctx):
            return

        data = []
        url = Storage().get(self)['predictions_thread']

        if not url or urlparse(url).netloc not in "www.transfermarkt.de":
            await ctx.send(Lang.lang(self, 'scrape_incorrect_url', url))
            return

        botmessage = await ctx.send(Lang.lang(self, 'scrape_start', url))
        async with ctx.typing():
            while True:
                response = requests.get(url, headers=Config().get(self)['user_agent'])
                soup = BeautifulSoup(response.text, "html.parser")

                posts = soup.find_all('div', 'box')
                for p in posts:
                    p_time = p.find_all('div', 'post-header-datum')
                    p_user = p.find_all('a', 'forum-user')
                    p_data = p.find_all('div', 'forum-post-data')
                    if p_user:
                        data.append({
                            'user': p_user[0].text,
                            'time': p_time[0].text.strip(),
                            'content': re.sub(r'(?:(?!\n)\s){2,}', ' ',
                                              p_data[0].text.replace('\u2013', '-')).split("\n")
                        })

                await botmessage.edit(content="{}\n{}".format(botmessage.content,
                                                               Lang.lang(self, 'scrape_intermediate', len(data))))
                next_page = soup.find_all('li', 'naechste-seite')
                if next_page and next_page[0].a:
                    url = urljoin(Storage().get(self)['predictions_thread'], next_page[0].a['href'])
                else:
                    await ctx.send(Lang.lang(self, 'scrape_end'))
                    break

            Storage().get(self)['predictions'] = data
            Storage().save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="extract", help="Extracts the predictions from the scraped result")
    async def set_extract(self, ctx):
        if not await self.trusted_check(ctx):
            return
        async with ctx.typing():
            c = self.get_api_client()
            matches = []
            predictions_by_user = {}
            data = Storage().get(self)['predictions']
            first_post = data[0]

            # Reading matches
            for line in first_post['content']:
                if line == "\u2022 \u2022 \u2022\r":
                    break
                if line == "":
                    continue
                if re.search(r"Uhr \|.+-", line):
                    matches.append(line)
            matchesre = "|".join([re.escape(x) for x in matches])  # for regex below

            # Reading posts
            for post in data[1:]:
                if post['content'] == first_post['content']:
                    continue

                predictions = {}
                for line in post['content']:
                    if line == "\u2022 \u2022 \u2022\r":
                        break
                    if line == "":
                        continue
                    result = re.search("(?P<match>{})\\D*(?P<goals_home>\\d+)\\s*\\D\\s*(?P<goals_away>\\d+)"
                                       .format(matchesre), line)
                    if result is not None:
                        groupdict = result.groupdict()
                        predictions[groupdict['match']] = (groupdict['goals_home'], groupdict['goals_away'])

                if predictions:
                    if post['user'] in predictions_by_user:
                        predictions_by_user[post['user']].update(predictions)
                    else:
                        predictions_by_user[post['user']] = predictions

            # Participants without predictions
            embed = discord.Embed(title=Lang.lang(self, 'extract_user_without_preds'))
            no_preds = []
            for i in range(1, 5):
                user_list = []
                participants = Storage().get(self)['participants'].get('liga{}'.format(i), [])
                for user in participants:
                    if user not in predictions_by_user:
                        user_list.append(user)
                    elif predictions_by_user[user] == {}:
                        no_preds.append(user)
                if user_list:
                    embed.add_field(name=Lang.lang(self, 'league', i), value=", ".join(user_list), inline=False)
            if no_preds:
                embed.description = Lang.lang(self, 'extract_user_no_preds', ", ".join(no_preds))
            if not embed.fields:
                embed.description = Lang.lang(self, 'extract_not_without_preds')
            await ctx.send(embed=embed)

            # Transforming for spreadsheet input
            data = []
            for i in range(1, 5):
                participants = Storage().get(self)['participants'].get('liga{}'.format(i), [])
                data.append([num for elem in [[user, None] for user in participants] for num in elem])
                for match in matches:
                    row = []
                    for user in participants:
                        row.extend(predictions_by_user.get(user, {}).get(match, [None, None]))
                    data.append(row)
                data.extend([[None], [None]])

            # Updating cells
            c.update("Aktuell!{}".format(Config().get(self)['predictions_range']), data, raw=False)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="archive", help="Archives the current matchday and clears the frontpage")
    async def set_archive(self, ctx):
        from googleapiclient.errors import HttpError
        if not await self.trusted_check(ctx):
            return

        async with ctx.typing():
            c = self.get_api_client()
            data = c.get(range="Aktuell!A1:CQ51", formatted=False)
            matchday = data[0][1]
            try:
                c.update(range="ST {}!A1:CQ51".format(matchday), values=data, raw=False)
            except HttpError:
                await ctx.send(Lang.lang(self, 'archive_page_missing', matchday))
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="thread", help="Sets the URL of the \"Tippabgabe-Thread\".")
    async def set_thread(self, ctx, url: str):
        if await self.trusted_check(ctx):
            Storage().get(self)['predictions_thread'] = url
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="mainthread", help="Sets the URL of the main thread.")
    async def set_mainthread(self, ctx, url: str):
        if await self.trusted_check(ctx):
            Storage().get(self)['main_thread'] = url
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="participants", alias="teilnehmer", help="Sets the participants of a league. "
                                                                        "Manager only.")
    async def set_participants(self, ctx, league: int, *participants):
        if await self.manager_check(ctx):
            Storage().get(self)['participants']['liga{}'.format(league)] = participants
            Storage().save(self)
            await ctx.send(Lang.lang(self, 'participants_added', len(participants), league))
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @spaetzle_set.command(name="matchday", help="Sets the matchday manually, but it's normally already done by "
                                                "set_matches.")
    async def set_matchday(self, ctx, matchday: int):
        if await self.trusted_check(ctx):
            Storage().get(self)['matchday'] = matchday
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    def get_matches_from_sheets(self):
        """
        Reads the matches from the sheet
        """
        c = self.get_api_client()
        matches = c.get("Aktuell!{}".format(Config().get(self)['matches_range']), formatted=False)

        # Extract matches
        self.matches.clear()
        for i in range(2, len(matches)):
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
            result = c.get("Aktuell!{}:{}".format(c.cellname(col1, row1 + 10), c.cellname(col1 + 1, row1 + 11)),
                           formatted=False)
            opponent = result[1][1]

            # Getting data / Opponent-dependent parts
            try:
                col2, row2 = self.get_user_cell(opponent)
            except UserNotFound:
                # Opponent not found
                matches, preds_h = c.get_multiple(["Aktuell!{}".format(Config().get(self)['matches_range']),
                                                   "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                          c.cellname(col1 + 1, row1 + 9))],
                                                  formatted=False)
                preds_a = [["–", "–"]] * 9
            else:
                # Opponent found
                matches, preds_h, preds_a = c.get_multiple(["Aktuell!{}".format(Config().get(self)['matches_range']),
                                                            "Aktuell!{}:{}".format(c.cellname(col1, row1 + 1),
                                                                                   c.cellname(col1 + 1, row1 + 9)),
                                                            "Aktuell!{}:{}".format(c.cellname(col2, row2 + 1),
                                                                                   c.cellname(col2 + 1, row2 + 9))],
                                                           formatted=False)
            # Fixing stuff
            matches = matches[2:]
            if len(matches) == 0:
                await ctx.send(Lang.lang(self, 'no_matches'))
                return
            if len(preds_h) == 0:
                preds_h = [["–", "–"]] * 9
            if len(preds_a) == 0:
                preds_a = [["–", "–"]] * 9
            for i in range(len(matches)):
                if matches[i][4] == "":
                    matches[i][4] = "–"
                if matches[i][5] == "":
                    matches[i][5] = "–"
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
            msg = ""
            msg += "{} Home - Away\u0020\u0020\u0020{}\u2026\u0020\u0020{}\u2026\n".format("\u2b1b",
                                                                                           user[:4], opponent[:4])
            for i in range(len(matches)):
                match = matches[i]
                pred_h = preds_h[i]
                pred_a = preds_a[i]
                emoji = self.match_status(datetime(1899, 12, 30) + timedelta(days=match[1] + match[2])).value
                msg += "{} {} {}:{} {}\u0020\u0020\u0020\u0020{}:{}\u0020\u0020\u0020\u0020{}:{}\n"\
                    .format(emoji, self.get_teamname_abbr(match[3]), match[4], match[5],
                            self.get_teamname_abbr(match[6]), pred_h[0], pred_h[1], pred_a[0], pred_a[1])

            embed = discord.Embed(title=user)
            embed.description = "{} [{}:{}] {}\n```{}```".format(user, result[0][0], result[1][0], opponent, msg)

            match_result = self.determine_winner(result[0][0], result[1][0], diff1, diff2)
            if match_result == MatchResult.HOME:
                embed.set_footer(text=Lang.lang(self, 'show_duel_footer_winner', user))
            elif match_result == MatchResult.AWAY:
                embed.set_footer(text=Lang.lang(self, 'show_duel_footer_winner', opponent))
            elif match_result == MatchResult.DRAW:
                embed.set_footer(text=Lang.lang(self, 'show_duel_footer_draw'))
            else:
                embed.set_footer(text=Lang.lang(self, 'show_duel_footer_normal', diff1, diff2))

        await ctx.send(embed=embed)

    @spaetzle.command(name="duels", aliases=["duelle"],
                      help="Displays the duels of observed users or the specified league")
    async def show_duels(self, ctx, league: str = None):
        if league is None:
            # Observed users
            await self.show_duels_observed(ctx)
        else:
            if league == "all":
                # All leagues
                await self.show_duels_all(ctx)
            elif league.isnumeric():
                # League
                await self.show_duels_league(ctx, int(league))
            else:
                await add_reaction(ctx.message, Lang.CMDERROR)

    async def show_duels_observed(self, ctx):
        async with ctx.typing():
            c = self.get_api_client()
            msg = ""

            data_ranges = []
            observed_users = Storage().get(self)['observed_users']

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
        await ctx.send(embed=discord.Embed(title="Duelle", description=msg))

    async def show_duels_league(self, ctx, league: int):
        async with ctx.typing():
            c = self.get_api_client()
            msg = ""

            data_range = "Aktuell!{}".format(Config().get(self)['duel_ranges'].get(league))
            if data_range is None:
                await ctx.send(Lang.lang(self, 'invalid_league'))
                return
            result = c.get(data_range)

            for duel in result:
                duel.extend([""] * (8 - len(duel)))
                msg += "{0} [{4}:{5}] {7}\n".format(*duel)
        await ctx.send(embed=discord.Embed(title="Duelle Liga {}".format(league), description=msg))

    async def show_duels_all(self, ctx):
        async with ctx.typing():
            c = self.get_api_client()
            data_ranges = ["Aktuell!J3:T11", "Aktuell!V3:AF11", "Aktuell!AH3:AR11", "Aktuell!AT3:BD11"]
            results = c.get_multiple(data_ranges)
            embed = discord.Embed(title="Duelle")

            for i in range(len(results)):
                msg = ""
                for duel in results[i]:
                    duel.extend([""] * (8 - len(duel)))
                    msg += "{0} [{4}:{5}] {7}\n".format(*duel)
                embed.add_field(name="Liga {}".format(i + 1), value=msg)
        await ctx.send(embed=embed)

    @spaetzle.command(name="matches", aliases=["spiele"], help="Displays the matches to be predicted")
    async def show_matches(self, ctx):
        async with ctx.typing():
            c = self.get_api_client()
            data = c.get("Aktuell!{}".format(Config().get(self)['matches_range']), formatted=False)
            matchday = data[0][0]
            matches = data[2:]

            if len(matches) == 0:
                await ctx.send(Lang.lang(self, 'no_matches'))
                return

            msg = ""
            for match in matches:
                date_time = datetime(1899, 12, 30) + timedelta(days=match[1] + match[2])
                emoji = self.match_status(date_time).value
                msg += "{0} {3} {1} {2} Uhr | {6} - {9} | {7}:{8}\n".format(emoji, date_time.strftime("%d.%m."),
                                                                            date_time.strftime("%H:%M"), *match)
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_matches', matchday), description=msg))

    @spaetzle.command(name="table", aliases=["tabelle", "league", "liga"],
                      help="Displays the table of a specific league")
    async def show_table(self, ctx, user_or_league: str = None):
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

            data_range = "Aktuell!{}".format(Config().get(self)['table_ranges'].get(league))
            if data_range is None:
                await ctx.send(Lang.lang(self, 'invalid_league'))
                return
            result = c.get(data_range)

            if not user_or_league.isnumeric():
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

    @spaetzle.command(name="rawpost", help="Lists all forum posts by a specified user")
    async def show_raw_posts(self, ctx, participant: str):
        if not await self.trusted_check(ctx):
            return
        
        forum_posts = Storage().get(self)['predictions']
        if len(forum_posts) < 1:
            await ctx.send(Lang.lang(self, 'no_saved_rawposts'))
            return
        first_post = forum_posts[0]
        posts_count = 0
        content = []
        for post in forum_posts:
            if post['content'] == first_post['content']:
                continue
            if participant.lower() in post['user'].lower():
                posts_count += 1
                content.append("\n———————————————\n" + post['time'])
                content.extend([x.strip() for x in post['content'] if x.strip()][:20])

        if posts_count == 0:
            await ctx.send(Lang.lang(self, 'raw_posts_prefix', 0))
        else:
            msgs = paginate(content, prefix=Lang.lang(self, 'raw_posts_prefix', posts_count))
            for msg in msgs:
                await ctx.send(msg)

    @spaetzle.group(name="trusted", help="Configures which users are allowed to edit")
    async def trusted(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle trusted list'))

    @trusted.command(name="list", help="Lists all trusted users")
    async def trusted_list(self, ctx):
        raw = [Config.get(self)['manager']] + Config.get(self)['trusted']
        trusted_users = []
        for user_id in raw:
            user = self.bot.guild.get_member(user_id)
            if user is None:
                user = self.bot.get_user(user_id)
            trusted_users.append(get_best_username(user))
        msg = "{} {}\n{} {}".format(Lang.lang(self, 'manager_prefix'), trusted_users[0],
                                    Lang.lang(self, 'trusted_prefix'), ", ".join(trusted_users[1:]))
        await ctx.send(msg)

    @trusted.command(name="add", help="Adds a user to the trusted list.")
    async def trusted_add(self, ctx, user: discord.User):
        if await self.manager_check(ctx):
            if user.id not in Config.get(self)['trusted']:
                Config.get(self)['trusted'].append(user.id)
                Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @trusted.command(name="del", help="Removes user from the trusted list")
    async def trusted_remove(self, ctx, user: discord.User):
        if await self.manager_check(ctx):
            if user.id in Config.get(self)['trusted']:
                Config.get(self)['trusted'].remove(user.id)
                Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @trusted.command(name="manager", help="Sets the manager")
    async def trusted_manager(self, ctx, user: discord.User):
        if ctx.author.id == Config.get(self)['manager'] or check_full_access(ctx.author):
            Config.get(self)['manager'] = user.id
            Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)

    @spaetzle.group(name="observe", help="Configure which users should be observed.")
    async def observe(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle observe list'))

    @observe.command(name="list", help="Lists the observed users")
    async def observe_list(self, ctx):
        if len(Storage().get(self)['observed_users']) == 0:
            msg = Lang.lang(self, 'no_observed_users')
        else:
            msg = "{} {}".format(Lang.lang(self, 'observe_prefix'), ", ".join(Storage().get(self)['observed_users']))
        await ctx.send(msg)

    @observe.command(name="add", help="Adds a user to be observed")
    async def observe_add(self, ctx, user):
        try:
            self.get_user_league(user)
        except UserNotFound:
            await ctx.send(Lang.lang(self, 'user_not_found'))
            return

        if user not in Storage().get(self)['observed_users']:
            Storage().get(self)['observed_users'].append(user)
            Storage().save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @observe.command(name="del", help="Removes a user from the observation")
    async def observe_remove(self, ctx, user):
        if user in Storage().get(self)['observed_users']:
            Storage().get(self)['observed_users'].remove(user)
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
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
