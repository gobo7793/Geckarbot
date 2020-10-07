import calendar
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands

from Geckarbot import BasePlugin
from botutils import sheetsclient, restclient
from botutils.converters import get_best_username, get_best_user
from botutils.permchecks import check_mod_access
from botutils.stringutils import paginate
from botutils.utils import add_reaction
from conf import Config, Storage, Lang
from plugins.spaetzle.subsystems import UserBridge, ObservedUsers
from plugins.spaetzle.utils import TeamnameDict, pointdiff_possible, determine_winner, MatchResult, match_status, \
    MatchStatus, get_user_league, get_user_cell, get_schedule, get_schedule_opponent


class UserNotFound(Exception):
    pass


class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.logger = logging.getLogger(__name__)
        self.matches = []
        self.matches_by_team = {}
        self.teamname_dict = TeamnameDict(self)
        self.userbridge = UserBridge(self)
        self.get_matches_from_sheets()

    def default_config(self):
        return {
            'manager': 0,
            'trusted': [],
            'spaetzledoc_id': "1ZzEGP_J9WxJGeAm1Ri3er89L1IR1riq7PH2iKVDmfP8",
            'matches_range': "B1:H11",
            'duel_ranges': {
                1: "K3:U11",
                2: "W3:AG11",
                3: "AI3:AS11",
                4: "AU3:BE11"
            },
            'table_ranges': {
                1: "K14:U31",
                2: "W14:AG31",
                3: "AI14:AS31",
                4: "AU15:BE33"
            },
            'predictions_range': "BH2:CU49",
            'all_duels_range': "K3:BE12",
            'archive_range': "A1:CU51",
            'user_agent': {
                'user-agent': "Geckarbot/{}".format(self.bot.VERSION)
            },
            'danny_id': 0,
            'danny_users': []
        }

    def default_storage(self):
        return {
            'matchday': 0,
            'main_thread': None,
            'predictions_thread': None,
            'discord_user_bridge': {},
            'observed_users': [],
            'participants': {},
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
        return sheetsclient.Client(self.bot, Config().get(self)['spaetzledoc_id'])

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

    @commands.command(name="goal", help="Scores a goal for a team (Spätzle-command)")
    async def goal(self, ctx, team, goals: int = None):
        abbr = self.teamname_dict.get_abbr(team)
        if abbr is None:
            await ctx.send(Lang.lang(self, 'team_not_found', team))
        else:
            async with ctx.typing():
                c = self.get_api_client()
                match = self.matches_by_team[abbr]
                if match_status(match['match_date_time']) == MatchStatus.UPCOMING:
                    await ctx.send(Lang.lang(self, 'match_is_in_future'))
                    return
                match[abbr]['goals'] = goals if goals is not None else match[abbr]['goals'] + 1

                if abbr == self.teamname_dict.get_abbr(match['team_home']):
                    msg = "{0} [**{1}**:{3}] {2}"
                else:
                    msg = "{0} [{1}:**{3}**] {2}"
                msg = msg.format(match['team_home'], match[self.teamname_dict.get_abbr(match['team_home'])]['goals'],
                                 match['team_away'], match[self.teamname_dict.get_abbr(match['team_away'])]['goals'])
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
        pred_urlpath = pred_thread = Storage().get(self)['predictions_thread']
        if pred_thread:
            pred_urlpath = urlparse(pred_thread).path.split("/")
            pred_urlpath = pred_urlpath[1] if len(pred_urlpath) > 0 else None
        main_urlpath = main_thread = Storage().get(self)['main_thread']
        if main_thread:
            main_urlpath = urlparse(main_thread).path.split("/")
            main_urlpath = main_urlpath[1] if len(main_urlpath) > 0 else None
        spreadsheet = "https://docs.google.com/spreadsheets/d/{}".format(Config().get(self)['spaetzledoc_id'])

        embed = discord.Embed(title="Spätzle(s)-Tippspiel", description=Lang.lang(self, 'info'))
        embed.add_field(name=Lang.lang(self, 'title_spreadsheet'),
                        value="[{}\u2026]({})".format(spreadsheet[:50], spreadsheet), inline=False)
        embed.add_field(name=Lang.lang(self, 'title_main_thread'),
                        value="[{}]({})".format(main_urlpath, main_thread))
        embed.add_field(name=Lang.lang(self, 'title_predictions_thread'),
                        value="[{}]({})".format(pred_urlpath, pred_thread))
        await ctx.send(embed=embed)

    @spaetzle.command(name="link", help="Get the link to the spreadsheet")
    async def spaetzle_doc_link(self, ctx):
        await ctx.send("<https://docs.google.com/spreadsheets/d/{}>".format(Config().get(self)['spaetzledoc_id']))

    @spaetzle.command(name="user", help="Connects your discord user with a specific spaetzle user")
    async def bridge_user(self, ctx, user=None):
        if user is None:
            success = self.userbridge.cut_bridge(ctx)
        else:
            success = self.userbridge.add_bridge(ctx, user)

        if success:
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await ctx.send(Lang.lang(self, 'user_not_bridged'))

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
                home = self.teamname_dict.get_abbr(match.get('Team1', {}).get('TeamName', 'n.a.'))
                away = self.teamname_dict.get_abbr(match.get('Team2', {}).get('TeamName', 'n.a.'))
                match_dict = {
                    'match_date_time': datetime.strptime(match.get('MatchDateTime', '0001-01-01T01:01:01'),
                                                         "%Y-%m-%dT%H:%M:%S"),
                    'team_home': self.teamname_dict.get_long(home),
                    'team_away': self.teamname_dict.get_long(away),
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
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_matchday', matchday), description=msg))

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
                    1: get_schedule(self, 1, matchday),
                    2: get_schedule(self, 2, matchday),
                    3: get_schedule(self, 3, matchday),
                    4: get_schedule(self, 4, matchday)
                }
                embed.title = Lang.lang(self, 'title_matchday_duels', matchday)
            else:
                schedules = {
                    league: get_schedule(self, league, matchday)
                }
                embed.title = Lang.lang(self, 'title_matchday_league', matchday, league)

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
                maxduels = len(max(data.values(), key=len))
                combined_data = [x[:] for x in [[]] * maxduels]
                for values in data.values():
                    values.extend([[None]*8] * (maxduels - len(values)))
                    for i in range(maxduels):
                        combined_data[i].extend(values[i] + [None] * 4)
                c.update("Aktuell!{}".format(Config().get(self)['all_duels_range']), combined_data)
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
            forumuser_list = set()
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
                forumuser_list.add(post['user'])
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

            # Participants without predictions / Unknown user
            embed = discord.Embed(title=Lang.lang(self, 'extract_user_without_preds'))
            no_preds = []
            for i in range(1, 5):
                user_list = []
                participants = Storage().get(self)['participants'].get(i, [])
                forumuser_list.difference_update(participants)
                for user in participants:
                    if user not in predictions_by_user:
                        user_list.append(user)
                    elif predictions_by_user[user] == {}:
                        no_preds.append(user)
                if user_list:
                    embed.add_field(name=Lang.lang(self, 'league', i), value=", ".join(user_list), inline=False)
            if forumuser_list:
                embed.add_field(name=Lang.lang(self, 'unknown_users'), value=", ".join(forumuser_list))
            if no_preds:
                embed.description = Lang.lang(self, 'extract_user_no_preds', ", ".join(no_preds))
            if not embed.fields:
                embed.description = Lang.lang(self, 'extract_not_without_preds')
            await ctx.send(embed=embed)

            # Transforming for spreadsheet input
            data = []
            for i in range(1, 5):
                participants = Storage().get(self)['participants'].get(i, [])
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
            data = c.get(range="Aktuell!{}".format(Config().get(self)['archive_range']), formatted=False)
            matchday = data[0][1]
            try:
                c.update(range="ST {}!{}".format(matchday, Config().get(self)['archive_range']),
                         values=data, raw=False)
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
            Storage().get(self)['participants'][league] = participants
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

    @spaetzle_set.command(name="config", help="Sets general config values for the plugin.",
                          usage="<path...> <value>")
    async def set_config(self, ctx, *args):
        if not ctx.author.id == Config.get(self)['manager'] and not check_mod_access(ctx.author):
            return
        if len(args) < 1:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return
        if len(args) == 1:
            await ctx.send(Lang.lang(self, 'not_enough_args'))
        else:
            config = Config().get(self)
            path = args[:-2]
            key = args[-2]
            value = args[-1]

            try:
                value = json.loads(value)
            except json.decoder.JSONDecodeError:
                pass

            try:
                key = int(key)
            except ValueError:
                pass

            for step in path:
                try:
                    step = int(step)
                except ValueError:
                    pass
                config = config.get(step)
                if config is None:
                    await add_reaction(ctx.message, Lang.CMDERROR)
                    return

            old_value = config.get(key)
            embed = discord.Embed(title="'{}'".format("/".join(args[:-1])))
            embed.add_field(name=Lang.lang(self, 'old_value'), value=str(old_value), inline=False)
            embed.add_field(name=Lang.lang(self, 'new_value'), value=value, inline=False)
            config[key] = value
            Config().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            await ctx.send(embed=embed)

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
            home = self.teamname_dict.get_abbr(match[3])
            away = self.teamname_dict.get_abbr(match[6])
            match_dict = {
                'match_date_time': datetime(1899, 12, 30) + timedelta(days=match[1] + match[2]),
                'team_home': self.teamname_dict.get_long(home),
                'team_away': self.teamname_dict.get_long(away),
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
                user = self.userbridge.get_user(ctx)
                if user is None:
                    await ctx.send(Lang.lang(self, 'user_not_bridged'))
                    return
            c = self.get_api_client()

            try:
                col1, row1 = get_user_cell(self, user)
            except UserNotFound:
                await ctx.send(Lang.lang(self, 'user_not_found'))
                return
            result = c.get("Aktuell!{}:{}".format(c.cellname(col1, row1 + 10), c.cellname(col1 + 1, row1 + 11)),
                           formatted=False)
            opponent = result[1][1]

            # Getting data / Opponent-dependent parts
            try:
                col2, row2 = get_user_cell(self, opponent)
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
            preds_h.extend([["-", "-"]] * (len(matches) - len(preds_h)))
            preds_a.extend([["-", "-"]] * (len(matches) - len(preds_a)))
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
                if match_status(datetime(1899, 12, 30)
                                + timedelta(days=matches[i][1] + matches[i][2])) == MatchStatus.CLOSED:
                    continue
                diff = pointdiff_possible(matches[i][4:6], preds_h[i], preds_a[i])
                diff1 += diff[0]
                diff2 += diff[1]

            # Producing the message
            msg = ""
            msg += ":soccer: `Home - Away\u0020\u0020\u0020" \
                   "{}\u2026\u0020\u0020{}\u2026`\n".format(user[:4], opponent[:4])
            for i in range(len(matches)):
                match = matches[i]
                pred_h = preds_h[i]
                pred_a = preds_a[i]
                emoji = match_status(datetime(1899, 12, 30) + timedelta(days=match[1] + match[2])).value
                msg += "{} `{} {}:{} {}\u0020\u0020\u0020\u0020{}:{}\u0020\u0020\u0020\u0020{}:{} `\n"\
                    .format(emoji, self.teamname_dict.get_abbr(match[3]), match[4], match[5],
                            self.teamname_dict.get_abbr(match[6]), pred_h[0], pred_h[1], pred_a[0], pred_a[1])

            embed = discord.Embed(title="{} [{}:{}] {}".format(user, result[0][0], result[1][0], opponent))
            embed.description = msg

            match_result = determine_winner(result[0][0], result[1][0], diff1, diff2)
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
                      help="Displays the duels of observed users or the specified league",
                      usage="[\u00a0|<league_number>|all]")
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
            observed_users = ObservedUsers(self).get_users()

            if len(observed_users) == 0:
                msg = Lang.lang(self, 'no_observed_users')
            else:
                for user in observed_users:
                    try:
                        col, row = get_user_cell(self, user)
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
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_duels'), description=msg))

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
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_duels_league', league), description=msg))

    async def show_duels_all(self, ctx):
        async with ctx.typing():
            c = self.get_api_client()
            data_ranges = list(Config().get(self)['duel_ranges'].values())
            results = c.get_multiple(data_ranges)
            embed = discord.Embed(title=Lang.lang(self, 'title_duels'))

            for i in range(len(results)):
                msg = ""
                for duel in results[i]:
                    duel.extend([""] * (8 - len(duel)))
                    msg += "{0}\u00a0[{4}:{5}]\u00a0{7}\n".format(*duel)
                embed.add_field(name=Lang.lang(self, 'title_league', i + 1), value=msg)
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
                emoji = match_status(date_time).value
                msg += "{0} {3} {1} {2} Uhr | {6} - {9} | {7}:{8}\n".format(emoji, date_time.strftime("%d.%m."),
                                                                            date_time.strftime("%H:%M"), *match)
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_matches', matchday), description=msg))

    @spaetzle.command(name="table", aliases=["tabelle", "league", "liga"],
                      help="Displays the table of a specific league")
    async def show_table(self, ctx, user_or_league: str = None):
        async with ctx.typing():
            c = self.get_api_client()

            if user_or_league is None:
                user_or_league = self.userbridge.get_user(ctx)
                if user_or_league is None:
                    await ctx.send(Lang.lang(self, 'user_not_bridged'))
                    return

            try:
                # League
                league = int(user_or_league)
            except ValueError:
                # User
                try:
                    league = int(get_user_league(self, user_or_league))
                except (ValueError, UserNotFound):
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
            embed = discord.Embed(title=Lang.lang(self, 'title_table', league), description=msg)
            embed.set_footer(text=Lang.lang(self, 'table_footer'))
        await ctx.send(embed=embed)

    @spaetzle.command(name="fixtures", help="Lists fixtures for a specific participant")
    async def show_fixtures(self, ctx, user=None):
        if user is None:
            user = self.userbridge.get_user(ctx)
            if user is None:
                await ctx.send(Lang.lang(self, 'user_not_bridged'))
                return

        msg = ""
        try:
            for i in range(1, 18):
                msg += "{} | {}\n".format(i, get_schedule_opponent(self, user, i))
        except UserNotFound:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'user_not_found'))
            return

        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_opponent', user), description=msg))

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

    @spaetzle.command(name="danny", help="Sends Danny the predictions of the participants who also take part in his"
                                         "Bundesliga prediction game.")
    async def danny_dm(self, ctx, *users):
        danny_id = Config().get(self)['danny_id']
        if not danny_id:
            await ctx.send(Lang.lang(self, 'danny_no_id'))
        if await self.manager_check(ctx) or ctx.author.id == danny_id:
            async with ctx.typing():
                c = self.get_api_client()
                danny = get_best_user(danny_id)
                data_ranges = ["Aktuell!{}".format(Config().get(self)['matches_range'])]
                if len(users) == 0:
                    users = Config().get(self)['danny_users']
                    if len(users) == 0:
                        await ctx.send(Lang.lang(self, 'danny_no_users'))
                for user in users:
                    col, row = get_user_cell(self, user)
                    if col is not None:
                        data_ranges.append("Aktuell!{}:{}".format(c.cellname(col, row), c.cellname(col + 1, row + 10)))
                result = c.get_multiple(data_ranges, formatted=False)
                matchday = result[0][0][0]
                matches = result[0][2:]
                preds = result[1:]

                embeds = []
                for p in preds:
                    embed = discord.Embed(title="**ST {} - {}**".format(matchday, p[0][0]))
                    msg = ""
                    matches_txt = []
                    for i in range(len(matches)):
                        if len(p[i+1]) < 2:
                            p[i+1] = ["-", "-"]
                        matches_txt.append("{} - {}".format(matches[i][3], matches[i][6]))
                    maxlength = len(max(matches_txt, key=len))
                    for i in range(len(matches_txt)):
                        msg += "{}{} {}:{}\n".format(matches_txt[i], " " * (maxlength - len(matches_txt[i])), *p[i+1])
                    embed.description = "```{}```".format(msg)
                    embeds.append(embed)

            for embed in embeds:
                await danny.send(embed=embed)
            await ctx.send(Lang.lang(self, 'danny_done', ", ".join(users)))

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
        if ctx.author.id == Config.get(self)['manager'] or check_mod_access(ctx.author):
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
        if len(ObservedUsers(self).get_users()) == 0:
            msg = Lang.lang(self, 'no_observed_users')
        else:
            msg = "{} {}".format(Lang.lang(self, 'observe_prefix'), ", ".join(ObservedUsers(self).get_users()))
        await ctx.send(msg)

    @observe.command(name="add", help="Adds a user to be observed")
    async def observe_add(self, ctx, user):
        if ObservedUsers(self).add_user(user):
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await ctx.send(Lang.lang(self, 'user_not_found'))

    @observe.command(name="del", help="Removes a user from the observation")
    async def observe_remove(self, ctx, user):
        if ObservedUsers(self).del_user(user):
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
                                                             match.get(self.teamname_dict.get_abbr(home)).get('goals'),
                                                             match.get(self.teamname_dict.get_abbr(away)).get('goals'))
        await ctx.send(embed=discord.Embed(title="self.matches", description=msg))
