import inspect
import json
import logging
import re
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands
from discord.ext.commands import MissingRequiredArgument

from Geckarbot import BasePlugin
from botutils import sheetsclient, restclient
from botutils.converters import get_best_user, get_best_username
from botutils.permchecks import check_mod_access
from botutils.sheetsclient import CellRange, Cell
from botutils.stringutils import paginate, format_andlist
from botutils.utils import add_reaction
from data import Config, Storage, Lang
from plugins.spaetzle.subsystems import UserBridge, Observed, Trusted
from plugins.spaetzle.utils import TeamnameDict, pointdiff_possible, determine_winner, MatchResult, match_status, \
    get_user_league, get_user_cell, get_schedule, get_schedule_opponent, UserNotFound, \
    convert_to_datetime, get_participant_history, duel_points
from subsystems.helpsys import DefaultCategories
from subsystems.liveticker import MatchStatus


class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):
    """Plugin for the Spaetzle(s)-Tippspiel"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self, category=DefaultCategories.SPORT)

        self.logger = logging.getLogger(__name__)
        self.teamname_dict = TeamnameDict(self)
        self.userbridge = UserBridge(self)

    def default_config(self):
        return {
            'manager': [],
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
            'predictions_ranges': {
                1: "BH2:CQ11",
                2: "BH14:CQ23",
                3: "BH26:CQ35",
                4: "BH38:CQ47"
            },
            'findreplace_matchday_range': "K34:BE51",
            'user_agent': {
                'user-agent': "Geckarbot/{}".format(self.bot.VERSION)
            },
            'danny_id': 0,
            'danny_users': []
        }

    def default_storage(self, container=None):
        if container is None:
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
                }
            }
        if container == 'forumposts':
            return []
        return {}

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format("_".join(command.qualified_name.split())))

    def command_description(self, command):
        name = "_".join(command.qualified_name.split())
        lang_name = "description_{}".format(name)
        result = Lang.lang(self, lang_name)
        return result if result != lang_name else Lang.lang(self, "help_{}".format(name))

    def get_api_client(self):
        """Returns sheetsclient"""
        return sheetsclient.Client(self.bot, Config().get(self)['spaetzledoc_id'])

    @commands.group(name="spaetzle", aliases=["spätzle", "spätzles"])
    async def cmd_spaetzle(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle info'))

    @cmd_spaetzle.command(name="info")
    async def cmd_spaetzle_info(self, ctx):
        """Sends info about the Spaetzles-Tippspiel"""
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

    @cmd_spaetzle.command(name="link")
    async def cmd_spaetzle_doc_link(self, ctx):
        """Sends the link to the spreadsheet"""
        await ctx.send("<https://docs.google.com/spreadsheets/d/{}>".format(Config().get(self)['spaetzledoc_id']))

    @cmd_spaetzle.command(name="user")
    async def cmd_bridge_user(self, ctx, user=None):
        """Connects a discord user with a specific spaetzle user"""
        if user is None:
            success = self.userbridge.cut_bridge(ctx)
        else:
            success = self.userbridge.add_bridge(ctx, user)

        if success:
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await ctx.send(Lang.lang(self, 'user_not_bridged'))

    @cmd_spaetzle.group(name="set")
    async def cmd_spaetzle_set(self, ctx):
        """Set data about next matchday etc"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.cmd_spaetzle_set)

    @cmd_spaetzle_set.command(name="matches", aliases=["spiele"])
    async def cmd_set_matches(self, ctx, matchday: int = None):
        """Sets the matches of the upcoming or running matchday"""
        if not await Trusted(self).is_trusted(ctx):
            return
        async with ctx.typing():
            # Request data
            if matchday:
                match_list = restclient.Client("https://www.openligadb.de/api").make_request(
                    "/getmatchdata/bl1/2020/{}".format(str(matchday)))
                regs = self.bot.liveticker.search(plugin=self)
                for src in regs.values():
                    for leag in src.values():
                        for reg in leag:
                            reg.deregister()
            else:
                reg = await self._start_liveticker()
                matchday = reg.league_reg.matchday()
                match_list = reg.league_reg.matches

            # Extract matches
            c = self.get_api_client()
            values = [[matchday], [None]]
            match_ids = []
            for match in match_list:
                match_ids.append(match.get('MatchID'))

                date_time = datetime.strptime(match.get('MatchDateTime', '0001-01-01T01:01:01'), "%Y-%m-%dT%H:%M:%S")
                date_formula = '=IF(DATE({};{};{}) + TIME({};{};0) < F12;0;"")'.format(*list(date_time.timetuple()))
                if date_time < datetime.now():
                    score1 = max(0, 0, *(g.get('ScoreTeam1', 0) for g in match.get('Goals', [])))
                    score2 = max(0, 0, *(g.get('ScoreTeam2', 0) for g in match.get('Goals', [])))
                else:
                    score1, score2 = date_formula, date_formula
                values.append([['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][date_time.weekday()],
                               date_time.strftime("%d.%m.%Y"),
                               date_time.strftime("%H:%M"),
                               self.teamname_dict.get_long(match.get('Team1', {}).get('TeamName', 'n.a.')),
                               score1,
                               score2,
                               self.teamname_dict.get_long(match.get('Team2', {}).get('TeamName', 'n.a.'))])

            # Put matches into spreadsheet
            c.update("Aktuell!{}".format(Config().get(self)['matches_range']), values, raw=False)

            # Set matchday and match_ids
            Storage().get(self)['match_ids'] = match_ids
            Storage().get(self)['matchday'] = matchday
            Storage().save(self)

            msg = ""
            for row in values[2:]:
                msg += "{0} {1} {2} Uhr | {3} - {6}\n".format(*row)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_matchday', matchday), description=msg))

    @cmd_spaetzle_set.command(name="duels", aliases=["duelle"])
    async def cmd_set_duels(self, ctx, matchday: int = None, league: int = None):
        """Sets duels for the matchday"""
        if not await Trusted(self).is_trusted(ctx):
            return
        if matchday is None:
            matchday = Storage().get(self)['matchday']
        matchday %= 17
        if matchday not in range(1, 18):
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'matchday_out_of_range'))
            return
        if league is not None and league not in Config().get(self)['duel_ranges'].keys():
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_league'))
            return

        async with ctx.typing():
            c = self.get_api_client()
            embed = discord.Embed()
            duel_ranges = Config().get(self)['duel_ranges']
            if league is None:
                league_list = duel_ranges.keys()
                embed.title = Lang.lang(self, 'title_matchday_duels', matchday)
            else:
                league_list = [league]
                embed.title = Lang.lang(self, 'title_matchday_league', matchday, league)

            data = {}
            for leag in league_list:
                msg = ""
                data[duel_ranges[leag]] = []
                schedule = get_schedule(self, leag, matchday)
                for duel in schedule:
                    msg += "{} - {}\n".format(*duel)
                    p = Storage().get(self)['participants'][leag]
                    home_fx = "={}".format(Cell(p.index(duel[0]) * 2 + 1, 11, CellRange.from_a1(
                        Config().get(self)['predictions_ranges'][leag])).cellname())
                    away_fx = "={}".format(Cell(p.index(duel[1]) * 2 + 1, 11, CellRange.from_a1(
                        Config().get(self)['predictions_ranges'][leag])).cellname())
                    data[duel_ranges[leag]].append([duel[0], None, None, None, home_fx, away_fx, None, duel[1]])
                if len(league_list) > 1:
                    embed.add_field(name="Liga {}".format(leag), value=msg)
                else:
                    embed.description = msg
            message = await ctx.send(embed=embed)

            c.update_multiple(data, raw=False)
        await add_reaction(message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="scrape")
    async def cmd_set_scrape(self, ctx, url=None):
        """Scrapes the predictions thread for forum posts"""
        if not await Trusted(self).is_trusted(ctx):
            return

        data = []
        if url is None:
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

            Storage().get(self, container='forumposts')[:] = data
            Storage().save(self, container='forumposts')
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="extract")
    async def cmd_set_extract(self, ctx):
        """Extracts the predictions from the scraped result"""
        if not await Trusted(self).is_trusted(ctx):
            return
        async with ctx.typing():
            c = self.get_api_client()
            matches = []
            predictions_by_user = {}
            forumuser_list = set()
            data = Storage().get(self, container='forumposts')
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
            data = {}
            participants = Storage().get(self)['participants']
            for leag, p in participants.items():
                data["Aktuell!{}".format(Config().get(self)['predictions_ranges'][leag])] = [[num for elem in
                                                                                              [[user, None] for user in
                                                                                               p] for num in elem]]
                for match in matches:
                    row = []
                    for user in p:
                        row.extend(predictions_by_user.get(user, {}).get(match, [None, None]))
                    data["Aktuell!{}".format(Config().get(self)['predictions_ranges'][leag])].append(row)

            # Updating cells
            c.update_multiple(data, raw=False)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="archive")
    async def cmd_set_archive(self, ctx):
        """Archives the current matchday and clears the frontpage"""
        if not await Trusted(self).is_trusted(ctx):
            return

        async with ctx.typing():
            c = self.get_api_client()

            duplicate = c.duplicate_and_archive_sheet("Aktuell", "ST {}".format(Storage().get(self)['matchday']))
            if duplicate:
                ranges = ["Aktuell!{}".format(Config().get(self)['matches_range'])]
                for r in Config().get(self)['duel_ranges'].values():
                    ranges.append("Aktuell!{}".format(r))
                for r_a1 in Config().get(self)['predictions_ranges'].values():
                    r = CellRange.from_a1(r_a1).expand(top=-1)
                    ranges.append("Aktuell!{}".format(r.rangename()))
                clear = c.clear_multiple(ranges)
                if clear:
                    replace = c.find_and_replace(find="ST {}".format(Storage().get(self)['matchday'] - 1),
                                                 replace="ST {}".format(Storage().get(self)['matchday']),
                                                 include_formulas=True, sheet="Aktuell",
                                                 range=Config().get(self)['findreplace_matchday_range'])
        if duplicate and clear and replace:
            Storage().get(self)['matchday'] += 1
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)

    @cmd_spaetzle_set.command(name="thread")
    async def cmd_set_thread(self, ctx, url: str):
        """Sets the URL of the Tippabgabe-Thread"""
        if await Trusted(self).is_trusted(ctx):
            Storage().get(self)['predictions_thread'] = url
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="mainthread")
    async def cmd_set_mainthread(self, ctx, url: str):
        """Sets the URL of the main thread"""
        if await Trusted(self).is_trusted(ctx):
            Storage().get(self)['main_thread'] = url
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="participants", alias="teilnehmer")
    async def cmd_set_participants(self, ctx, league: int, *participants):
        """Sets the participants of a league"""
        if await Trusted(self).is_manager(ctx):
            Storage().get(self)['participants'][league] = list(participants)
            Storage().save(self)
            await ctx.send(Lang.lang(self, 'participants_added', len(participants), league))
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="matchday", hidden=True)
    async def cmd_set_matchday(self, ctx, matchday: int):
        """Sets the matchday manually, but it's normally already done by set_matches"""
        if await Trusted(self).is_trusted(ctx):
            Storage().get(self)['matchday'] = matchday
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle_set.command(name="liveticker", hidden=True)
    async def cmd_set_liveticker(self, ctx):
        """Manually starts the liveticker for automatic score updates"""
        await self._start_liveticker()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _start_liveticker(self):
        """Registers a liveticker"""
        return await self.bot.liveticker.register(league="bl1", plugin=self, coro=self._liveticker_coro, periodic=True)

    async def _liveticker_coro(self, matches, *_):
        self.logger.debug("Spätzle score update started.")
        c = self.get_api_client()
        values = [[]] * 9

        # Build values
        for match_id, match in matches.items():
            if match_id in Storage().get(self)['match_ids'] and match['kickoff_time'] and \
                    match['kickoff_time'] < datetime.now() and not match['is_finished']:
                values[Storage().get(self)['match_ids'].index(match_id)] = [*match['score']]

        # Put scores into spreadsheet
        c.update(range="Aktuell!{}".format(CellRange.from_a1(Config.get(self)['matches_range']).expand(top=-2, left=-4)
                                           .rangename()),
                 values=values)
        self.logger.debug("Spätzle score update finished.")

    @cmd_spaetzle_set.command(name="config", usage="<path...> <value>")
    async def cmd_set_config(self, ctx, *args):
        """Sets general config values for the plugin"""
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

    @cmd_spaetzle.command(name="goal", hidden=True)
    async def cmd_goal(self, ctx, team, goals: int = None, goals_other: int = None):
        """Increments or sets the goal count in a given match"""
        name = self.teamname_dict.get_long(team)
        if name is None:
            await ctx.send(Lang.lang(self, 'team_not_found', team))
        else:
            async with ctx.typing():
                c = self.get_api_client()
                data = c.get(Config().get(self)['matches_range'], formatted=False)
                for i in range(2, len(data)):
                    row = data[i]
                    if len(row) >= 7:
                        if row[3] == name:
                            values = [goals if goals is not None else row[4] + 1 if row[4] else 1,
                                      goals_other if goals_other is not None else row[5] if row[5] else 0]
                            await ctx.send("{} [**{}**:{}] {}".format(row[3], *values, row[6]))
                            index = i
                            break
                        if row[6] == name:
                            values = [goals_other if goals_other is not None else row[4] if row[4] else 0,
                                      goals if goals is not None else row[5] + 1 if row[5] else 1]
                            await ctx.send("{} [{}:**{}**] {}".format(row[3], *values, row[6]))
                            index = i
                            break
                else:
                    await ctx.send(Lang.lang(self, 'team_not_found', team))
                    return

                cellrange = CellRange.from_a1(Config().get(self)['matches_range']).expand(top=-index, left=-4)
                c.update(range="Aktuell!{}".format(cellrange.rangename()), values=[values], raw=False)

            await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle.command(name="duel", aliases=["duell"])
    async def cmd_show_duel_single(self, ctx, user=None):
        """Displays the duel of a specific user"""
        async with ctx.typing():
            if user is None:
                user = self.userbridge.get_user(ctx)
                if user is None:
                    await ctx.send(Lang.lang(self, 'user_not_bridged'))
                    return
            c = self.get_api_client()

            try:
                cell1 = get_user_cell(self, user)
            except UserNotFound:
                await ctx.send(Lang.lang(self, 'user_not_found', user))
                return
            result = c.get("Aktuell!{}".format(CellRange(cell1.translate(0, 10), 2, 2).rangename()),
                           formatted=False)
            opponent = result[1][1]

            # Getting data / Opponent-dependent parts
            try:
                cell2 = get_user_cell(self, opponent)
            except UserNotFound:
                # Opponent not found
                matches, preds_h = c.get_multiple(
                    ["Aktuell!{}".format(Config().get(self)['matches_range']),
                     "Aktuell!{}".format(CellRange(cell1.translate(0, 1), 2, 9).rangename())], formatted=False)
                preds_a = [["–", "–"]] * 9
            else:
                # Opponent found
                matches, preds_h, preds_a = c.get_multiple(
                    ["Aktuell!{}".format(Config().get(self)['matches_range']),
                     "Aktuell!{}".format(CellRange(cell1.translate(0, 1), 2, 9).rangename()),
                     "Aktuell!{}".format(CellRange(cell2.translate(0, 1), 2, 9).rangename())], formatted=False)
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
                if match_status(matches[i][1], matches[i][2]) == MatchStatus.COMPLETED:
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
                emoji = match_status(match[1], match[2]).value
                msg += "{} `{} {}:{} {}\u0020\u0020\u0020\u0020{}:{}\u0020\u0020\u0020\u0020{}:{} `\n" \
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

    @cmd_spaetzle.command(name="duels", aliases=["duelle"], usage="[\u00a0|<league_number>|all]")
    async def cmd_show_duels(self, ctx, league: str = None):
        """Displays a collection of duels (observed participants or leagues)"""
        if league is None:
            # Observed users
            await self.cmd_show_duels_observed(ctx)
        else:
            if league == "all":
                # All leagues
                await self.cmd_show_duels_all(ctx)
            elif league.isnumeric():
                # League
                await self.cmd_show_duels_league(ctx, int(league))
            else:
                await add_reaction(ctx.message, Lang.CMDERROR)

    async def cmd_show_duels_observed(self, ctx):
        """Displays the duel scores of the observed participants"""
        async with ctx.typing():
            c = self.get_api_client()
            msg = ""

            data_ranges = []
            observed_users = Observed(self).get_all()

            if len(observed_users) == 0:
                msg = Lang.lang(self, 'no_observed_users')
            else:
                for user in observed_users:
                    try:
                        cell = get_user_cell(self, user)
                        data_ranges.append("Aktuell!{}".format(cell.cellname()))
                        data_ranges.append(
                            "Aktuell!{}".format(CellRange(cell.translate(0, 10), 2, 2).rangename()))
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

    async def cmd_show_duels_league(self, ctx, league: int):
        """Displays all duels of one league"""
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

    async def cmd_show_duels_all(self, ctx):
        """Displays all duels of all leagues"""
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

    @cmd_spaetzle.command(name="matches", aliases=["spiele"])
    async def cmd_show_matches(self, ctx):
        """Displays current matches"""
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
                date_time = convert_to_datetime(match[1], match[2])
                emoji = match_status(date_time).value
                msg += "{0} {3} {1} {2} Uhr | {6} - {9} | {7}:{8}\n".format(emoji, date_time.strftime("%d.%m."),
                                                                            date_time.strftime("%H:%M"), *match)
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_matches', matchday), description=msg))

    @cmd_spaetzle.command(name="table", aliases=["tabelle", "league", "liga"])
    async def cmd_show_table(self, ctx, user_or_league: str = None):
        """Displays the table of a specific league"""
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
                    await ctx.send(Lang.lang(self, 'user_not_found', user_or_league))
                    return

            table_range = Config().get(self)['table_ranges'].get(league)
            if table_range is None:
                await ctx.send(Lang.lang(self, 'invalid_league'))
                return
            result = c.get("Aktuell!{}".format(table_range))

            if not user_or_league.isnumeric():
                # Restrict the view to users area
                pos = None
                for i in range(len(result)):
                    pos = i if result[i][3].lower() == user_or_league.lower() else pos
                if pos is not None:
                    result = result[max(0, pos - 3):pos + 4]

            msg = ""
            for line in result:
                line.extend([''] * (11 - len(line)))
                msg += "{0}{1} | {4} | {7}:{9} {10} | {11}{0}\n".format("**" if line[3].lower() ==
                                                                        user_or_league.lower() else "", *line)
            embed = discord.Embed(title=Lang.lang(self, 'title_table', league), description=msg)
            embed.set_footer(text=Lang.lang(self, 'table_footer'))
        await ctx.send(embed=embed)

    @cmd_spaetzle.command(name="fixtures")
    async def cmd_show_fixtures(self, ctx, user=None):
        """Lists fixtures for a specific participant"""
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
            await ctx.send(Lang.lang(self, 'user_not_found', user))
            return

        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'title_opponent', user), description=msg))

    @cmd_spaetzle.command(name="rawpost")
    async def cmd_show_rawpost(self, ctx, participant: str):
        """List all scraped forum posts by a specific participant"""
        if not await Trusted(self).is_trusted(ctx):
            return

        forum_posts = Storage().get(self, container='forumposts')
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
                content.append("\n———————————————\n***{}** - {}*".format(post['user'], post['time']))
                content.extend([x.strip() for x in post['content'] if x.strip()][:20])

        if posts_count == 0:
            await ctx.send(Lang.lang(self, 'raw_posts_prefix', 0))
        else:
            msgs = paginate(content, prefix=Lang.lang(self, 'raw_posts_prefix', posts_count))
            for msg in msgs:
                await ctx.send(msg)

    @cmd_spaetzle.command(name="history")
    async def cmd_show_history(self, ctx, participant: str):
        """Displays the past matches of given participant"""
        async with ctx.typing():
            try:
                history_data = get_participant_history(self, participant)
            except UserNotFound:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'user_not_found', participant))
            except HTTPError:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'error_wrong_matchday?'))
            else:
                rows = []
                for md, pts, pts_opp, opp in history_data:
                    rows.append("{} | {} - {}:{}".format(md, opp, pts, pts_opp))
                await ctx.send(embed=discord.Embed(title=participant, description="\n".join(rows)))

    @cmd_spaetzle.command(name="purge")
    async def cmd_purge_user(self, ctx, participant: str):
        """Purges a participant from the """
        if not await Trusted(self).is_manager(ctx):
            return
        async with ctx.typing():
            try:
                history_data = get_participant_history(self, participant)
            except UserNotFound:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'user_not_found', participant))
            except HTTPError:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'error_wrong_matchday?'))
            else:
                msg = []
                correction = {}
                for md, pts, pts_opp, opp in history_data:
                    if str(pts).isnumeric():
                        msg.append("{0} | {1} - {2}:{3} \u2192 –:{3}".format(md, opp, pts, pts_opp))
                        correction[opp] = int(pts), duel_points(pts_opp, 0) - duel_points(pts_opp, pts)
                await ctx.send(embed=discord.Embed(title=participant, description="\n".join(msg)))
                # TODO automatic correction in spreadsheet

    @cmd_spaetzle.command(name="danny")
    async def cmd_danny_dm(self, ctx, *users):
        """Sends Danny (or whoever manages it) the predictions of the participants who also take part in his Bundesliga
        prediction game."""
        danny_id = Config().get(self)['danny_id']
        not_found_users = []
        if not danny_id:
            await ctx.send(Lang.lang(self, 'danny_no_id'))
        if await Trusted(self).is_manager(ctx, show_error=False) or ctx.author.id == danny_id:
            async with ctx.typing():
                c = self.get_api_client()
                danny = get_best_user(danny_id)
                data_ranges = ["Aktuell!{}".format(Config().get(self)['matches_range'])]
                if len(users) == 0:
                    users = Config().get(self)['danny_users']
                    if len(users) == 0:
                        await ctx.send(Lang.lang(self, 'danny_no_users'))
                else:
                    users = list(users)
                for user in users[:]:
                    try:
                        cell = get_user_cell(self, user)
                    except UserNotFound:
                        users.remove(user)
                        not_found_users.append(user)
                    else:
                        data_ranges.append("Aktuell!{}".format(CellRange(cell, 2, 11).rangename()))
                result = c.get_multiple(data_ranges, formatted=False)
                if not result[0]:
                    await ctx.send(Lang.lang(self, 'danny_empty'))
                    return
                matchday = result[0][0][0]
                matches = result[0][2:]
                preds = result[1:]

                embeds = []
                for p in preds:
                    embed = discord.Embed(title="**ST {} - {}**".format(matchday, p[0][0]))
                    msg = ""
                    matches_txt = []
                    for i in range(len(matches)):
                        if len(p[i + 1]) < 2:
                            p[i + 1] = ["-", "-"]
                        matches_txt.append("{} - {}".format(matches[i][3], matches[i][6]))
                    maxlength = len(max(matches_txt, key=len))
                    for i in range(len(matches_txt)):
                        msg += "{}{} {}:{}\n".format(matches_txt[i], " " * (maxlength - len(matches_txt[i])), *p[i + 1])
                    embed.description = "```{}```".format(msg)
                    embeds.append(embed)

            for embed in embeds:
                await danny.send(embed=embed)
            if not_found_users:
                await ctx.send(Lang.lang(self, 'danny_done_notfound', get_best_username(danny),
                                         format_andlist(users, Lang.lang(self, 'danny_and'),
                                                        Lang.lang(self, 'danny_nobody')),
                                         format_andlist(not_found_users, Lang.lang(self, 'danny_and'),
                                                        Lang.lang(self, 'danny_nobody'))))
            else:
                await ctx.send(Lang.lang(self, 'danny_done', get_best_username(danny),
                                         format_andlist(users, Lang.lang(self, 'danny_and'),
                                                        Lang.lang(self, 'danny_nobody'))))

    @cmd_spaetzle.group(name="trusted")
    async def cmd_trusted(self, ctx):
        """Configures which users are trusted for support"""
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle trusted list'))

    @cmd_trusted.command(name="list")
    async def cmd_trusted_list(self, ctx):
        """Lists all users that are either trusted or manager"""
        msg = "{} {}\n{} {}".format(
            Lang.lang(self, 'manager_prefix'), ", ".join(Trusted(self).get_manager_names(self.bot)),
            Lang.lang(self, 'trusted_prefix'), ", ".join(Trusted(self).get_trusted_names(self.bot)))
        await ctx.send(msg)

    @cmd_trusted.command(name="add")
    async def cmd_trusted_add(self, ctx, user: discord.User):
        """Adds a user to the trusted list"""
        await Trusted(self).add_trusted(ctx, user)

    @cmd_trusted.command(name="del")
    async def cmd_trusted_remove(self, ctx, user: discord.User):
        """Removes user from the trusted list"""
        await Trusted(self).remove_trusted(ctx, user)

    @cmd_spaetzle.group(name="manager")
    async def cmd_manager(self, ctx):
        """Configures which users are allowed to use all functions"""
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle trusted list'))

    @cmd_manager.command(name="add", help="Adds a manager.")
    async def cmd_manager_add(self, ctx, user: discord.User):
        """Adds manager"""
        await Trusted(self).add_manager(ctx, user)

    @cmd_manager.command(name="del")
    async def cmd_manager_remove(self, ctx, user: discord.User):
        """Removes manager"""
        await Trusted(self).remove_manager(ctx, user)

    @cmd_spaetzle.group(name="observe")
    async def cmd_observe(self, ctx, *args):
        """Configure which users should be observed. Redirects to add/del or adds given users anyway. Redirects to list
        without args"""
        if ctx.invoked_subcommand is None:
            if len(args) > 0:
                if args[0] in ("add", "del"):
                    if len(args) > 1:
                        await ctx.invoke(self.bot.get_command('spaetzle observe {}'.format(args[0])), *args[1:])
                    else:
                        raise MissingRequiredArgument(inspect.Parameter("user", inspect.Parameter.POSITIONAL_ONLY))
                else:
                    await self.cmd_observe_add(ctx, args[0], *args[1:])
            else:
                await ctx.invoke(self.bot.get_command('spaetzle observe list'))

    @cmd_observe.command(name="list")
    async def cmd_observe_list(self, ctx):
        """Lists the observed participants"""
        if len(Observed(self).get_all()) == 0:
            msg = Lang.lang(self, 'no_observed_users')
        else:
            msg = "{} {}".format(Lang.lang(self, 'observe_prefix'), ", ".join(Observed(self).get_all()))
        await ctx.send(msg)

    @cmd_observe.command(name="add")
    async def cmd_observe_add(self, ctx, user: str, *other: list):
        """Adds one or multiple participants to observation"""
        for u in (user,) + other:
            if not Observed(self).append(u):
                await ctx.send(Lang.lang(self, 'user_not_found', u))
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_observe.command(name="del")
    async def cmd_observe_remove(self, ctx, user: str, *other: list):
        """Removes one or multiple participants from observation"""
        for u in (user,) + other:
            if not Observed(self).remove(u):
                await ctx.send(Lang.lang(self, 'user_not_found', u))
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
