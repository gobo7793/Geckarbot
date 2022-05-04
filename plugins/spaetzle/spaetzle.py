import logging
import re
from datetime import datetime
from typing import Literal, List, Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from nextcord import Embed, Interaction
from nextcord.ext import commands
from nextcord.ext.commands import Context

from Geckarbot import BasePlugin
from base.data import Config, Lang, Storage
from botutils import sheetsclient, restclient
from botutils.sheetsclient import CellRange
from botutils.uiutils import SingleConfirmView, SingleItemView, CoroButton
from botutils.utils import helpstring_helper, add_reaction, paginate_embeds
from plugins.spaetzle.utils import SpaetzleUtils
from services.helpsys import DefaultCategories
from services.liveticker import LeagueRegistrationOLDB


class Plugin(BasePlugin, SpaetzleUtils, name="Spaetzle-Tippspiel"):
    """Plugin for the Spaetzle(s)-Tippspiel"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category=DefaultCategories.SPORT)
        self.migrate()
        SpaetzleUtils.__init__(self)

        self.logger = logging.getLogger(__name__)

    def default_config(self, container=None):
        return {
            '_config_version': 1,
            'ranges': {
                'duel_columns': "B:D",
                'league_rows': ["6:23", "25:42", "44:61", "63:80"],
                'matches': "P2:AG4",
                'opp_points_column': "AI:AI",
                'points_column': "AH:AH",
                'pred_columns': "O:AG",
                'table_columns': "F:M"
            },
            'matchday_shuffle': [7, 4, 11, 6, 3, 10, 12, 8, 5, 15, 9, 16, 1, 13, 0, 14, 2, 17],
            'participants_shuffle': [15, 11, 8, 17, 12, 16, 13, 9, 10, 2, 4, 5, 1, 6, 0, 7, 3, 14],
            'spaetzledoc_id': "1eUCYWLw09CBzxJj3Zx-t8ssVwdqsjRgzzj37paPtZIA",
        }

    def default_storage(self, container=None):
        return {
            '_storage_version': 1,
            'matchday': 0,
            'participants': [[], [], [], []],
            'predictions_thread': ""
        }

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def migrate(self):
        """Migrates config and storage to newer versions"""
        if Config().get(self).get('_config_version', 0) < 1:
            Config().set(self, self.default_config())
            Config().save(self)
        if Storage().get(self).get('_storage_version', 0) < 1:
            Storage().get(self)['participants'] = [[], [], [], []]
            Storage().get(self)['_storage_version'] = 1
            Storage().save(self)

    def get_api_client(self):
        """Returns sheetsclient"""
        return sheetsclient.Client(self.bot, Config().get(self)['spaetzledoc_id'])

    @commands.group(name="spaetzle", aliases=["spätzle", "spätzles"])
    async def cmd_spaetzle(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle info'))

    @cmd_spaetzle.command(name="info")
    async def cmd_spaetzle_info(self, ctx: Context):
        """Sends info about the Spaetzles-Tippspiel"""
        spreadsheet = f"https://docs.google.com/spreadsheets/d/{Config().get(self)['spaetzledoc_id']}"

        embed = Embed(title="Spätzle(s)-Tippspiel", description=Lang.lang(self, 'info'))
        embed.add_field(name=Lang.lang(self, 'title_spreadsheet'),
                        value=f"[{spreadsheet[:50]}\u2026]({spreadsheet})", inline=False)
        await ctx.send(embed=embed)

    @cmd_spaetzle.command(name="link")
    async def cmd_spaetzle_doc_link(self, ctx: Context):
        """Sends the link to the spreadsheet"""
        await ctx.send(f"<https://docs.google.com/spreadsheets/d/{Config().get(self)['spaetzledoc_id']}>")

    @cmd_spaetzle.group(name="setup")
    async def cmd_spaetzle_setup(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command('spaetzle setup matches'))
            await ctx.invoke(self.bot.get_command('spaetzle setup duels'))

    @cmd_spaetzle_setup.command(name="matches")
    async def cmd_spaetzle_setup_matches(self, ctx: Context):
        async def insert_to_spreadsheet(_b, interaction: Interaction):
            time_cells = []
            team_cells = []
            match_cells = []
            _matchday = interaction.message.embeds[0].title.split(" ")[-1]
            for row in interaction.message.embeds[0].description.split("\n"):
                dt, teams = row.split(" | ")
                kickoff_time = datetime.strptime(dt, "%a. %d.%m.%Y, %H:%M Uhr")
                home, away = teams.split(" - ")
                match = "{} - {}".format(Config().bot.liveticker.teamname_converter.get(home).abbr,
                                         Config().bot.liveticker.teamname_converter.get(away).abbr)
                time_cells.extend([kickoff_time.strftime("%d.%m.%Y %H:%M"), None])
                team_cells.extend([home, away])
                match_cells.extend([match, None])
            self.get_api_client().update(f"'ST {_matchday}'!{Config().get(self)['ranges']['matches']}",
                                         [time_cells, team_cells, match_cells], raw=False)

        matchday = Storage().get(self)['matchday']
        match_list = await LeagueRegistrationOLDB.get_matches_by_matchday(league="bl1", matchday=matchday)
        await ctx.send(embed=Embed(title=Lang.lang(self, 'matchday_x', matchday),
                                   description="\n".join(m.display_short() for m in match_list)),
                       view=SingleConfirmView(insert_to_spreadsheet, confirm_label=Lang.lang(self, 'confirm'),
                                              user_id=ctx.author.id))

    @cmd_spaetzle_setup.command(name="duels")
    async def cmd_spaetzle_setup_duels(self, ctx: Context):
        def calculate_schedule(_participants: List[Optional[str]]):
            matchday = Config().get(self)['matchday_shuffle'][(Storage().get(self)['matchday'] - 1) % 17]  # Shuffle
            _participants.extend([None] * max(0, 18 - len(_participants)))  # Extend if not enough participants
            _p = [_participants[j] for j in Config().get(self)['participants_shuffle']] + _participants[18:]  # Shuffle
            _p = _p[0:1] + _p[1:][matchday:] + _p[1:][:matchday]  # Rotate
            _schedule = [(_p[0], _p[1])]
            _schedule.extend((_p[2 + j], _p[-1 - j]) for j in range(len(_p) // 2 - 1))
            return _schedule

        async def insert_to_spreadsheet(button: CoroButton, _i):
            data_dict = {}
            _participants = Storage().get(self)['participants']
            _schedules: List[List[Tuple]] = button.view.data
            for j in range(len(_schedules)):
                opponent_cells = dict.fromkeys(_participants[j])
                duels_rows = []
                for p1, p2 in _schedules[j]:
                    p1_cellname = f"={self.get_participant_point_cellname(p1, league=j + 1)}"
                    p2_cellname = f"={self.get_participant_point_cellname(p2, league=j + 1)}"
                    if p1_cellname == "=None" or p2_cellname == "=None":
                        continue
                    opponent_cells[p1] = [p2_cellname]
                    opponent_cells[p2] = [p1_cellname]
                    duels_rows.extend(([None, p1, p1_cellname], [None, p2, p2_cellname]))
                league_rows = CellRange.from_a1(Config().get(self)['ranges']['league_rows'][j])
                duel_range = league_rows.overlay_range(
                    CellRange.from_a1(Config().get(self)['ranges']['duel_columns'])).rangename()
                opponent_range = league_rows.overlay_range(
                    CellRange.from_a1(Config().get(self)['ranges']['opp_points_column'])).rangename()
                data_dict[f"ST {Storage().get(self)['matchday']}!{duel_range}"] = duels_rows
                data_dict[f"ST {Storage().get(self)['matchday']}!{opponent_range}"] = list(opponent_cells.values())
            self.get_api_client().update_multiple(data_dict, raw=False)

        embed = Embed(title=Lang.lang(self, 'duels_mx', Storage().get(self)['matchday']))
        participants = Storage().get(self)['participants']
        schedules = []
        for i in range(len(participants)):
            schedules.append(schedule := calculate_schedule(participants[i]))
            embed.add_field(name=Lang.lang(self, 'league_x', i + 1), value="\n".join(f"{x} - {y}" for x, y in schedule))
        await ctx.send(embed=embed, view=SingleConfirmView(insert_to_spreadsheet, user_id=ctx.author.id,
                                                           confirm_label=Lang.lang(self, 'confirm'), data=schedules))

    @cmd_spaetzle.command(name="scrape")
    async def cmd_spaetzle_scrape(self, ctx: Context, url: str = None):
        async def continue_extract(button: CoroButton, interaction: Interaction):
            if button.data == interaction.user.id:
                button.view.stop()
                await ctx.invoke(self.bot.get_command("spaetzle extract"))

        init_content = ""
        post_list = {}
        original_url = url
        if url is None:
            url = Storage().get(self)['predictions_thread']

        if not url or urlparse(url).netloc not in "www.transfermarkt.de":
            await ctx.send(Lang.lang(self, 'scrape_incorrect_url', url))
            return

        botmessage = await ctx.send(Lang.lang(self, 'scrape_start', url))
        async with ctx.typing():
            while True:
                response = await restclient.Client("https://www.transfermarkt.de").request(urlparse(url).path,
                                                                                           parse_json=False)
                soup = BeautifulSoup(response, "html.parser")

                if not init_content:
                    init_post = soup.find(id="initialPost").find('div', 'forum-post-data')
                    init_content = re.sub(r'(?:(?!\n)\s){2,}', ' ', init_post.text.replace('\u2013', '-')).split("\n")
                posts = soup.find(id="postList").find_all('div', 'box')
                for p in posts:
                    p_time = p.find('div', 'post-header-datum')
                    p_user = p.find('a', 'forum-user')
                    p_data = p.find('div', 'forum-post-data')
                    p_id = p.find('span', 'link-zum-post')
                    if p_time and p_user and p_data:
                        post_list[p_id.text] = {
                            'user': p_user.text,
                            'time': p_time.text.strip(),
                            'link': p_id.a['href'],
                            'content': re.sub(r'(?:(?!\n)\s){2,}', ' ', p_data.text.replace('\u2013', '-')).split("\n")
                        }

                await botmessage.edit(content="{}\n{}".format(botmessage.content,
                                                              Lang.lang(self, 'scrape_intermediate', len(post_list))))
                next_page = soup.find_all('li', 'tm-pagination__list-item--icon-next-page')
                if next_page and next_page[0].a:
                    url = urljoin(Storage().get(self)['predictions_thread'], next_page[0].a['href'])
                else:
                    await ctx.send(Lang.lang(self, 'scrape_end'),
                                   view=SingleItemView(item=CoroButton(coro=continue_extract, data=ctx.author.id,
                                                                       label="!spaetzle extract")))
                    break

            Storage().set(self, {'init': init_content, 'posts': post_list, 'url': original_url}, container='forumposts')
            Storage().save(self, container='forumposts')
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle.command(name="extract")
    async def cmd_spaetzle_extract(self, ctx: Context):
        forumposts = Storage().get(self, container='forumposts')
        participants = Storage().get(self)['participants']
        matchday = Storage().get(self)['matchday']
        missing_participants: List[str] = []
        no_preds_but_post: List[str] = []

        await ctx.trigger_typing()

        # Matches from initial posts
        matches = []
        for line in forumposts['init']:
            if line == "\u2022 \u2022 \u2022\r":
                break
            if re.search(r"Uhr \|.+-", line):
                matches.append(line)

        # Extract predictions from posts
        predictions: Dict[str, Dict[str, Tuple[int, int]]] = {}
        found_users = set()
        for post in forumposts['posts'].values():
            found_users.add(post['user'])
            if post['user'] not in predictions:
                predictions[post['user']] = {}
            predictions[post['user']].update(self.extract_predictions(matches=matches, raw_post=post['content']))

        # Insert into spreadsheet
        data_dict = {}
        for league in range(len(participants)):
            l_data = []
            for p in participants[league]:
                p_data = [p]
                if not (p_preds := predictions.get(p, {})):
                    missing_participants.append(p)
                    if p in found_users:
                        no_preds_but_post.append(p)
                for m in matches:
                    p_data.extend(p_preds.get(m, ("–", "–")))
                l_data.append(p_data)
            data_range = CellRange.from_a1(Config().get(self)['ranges']['league_rows'][league]).overlay_range(
                CellRange.from_a1(Config().get(self)['ranges']['pred_columns'])).rangename()
            data_dict[f"ST {matchday}!{data_range}"] = l_data
        self.get_api_client().update_multiple(data_dict, raw=False)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

        # Output discord
        embed = Embed(title=Lang.lang(self, 'matchday_x', matchday))
        missing_preds = {}
        for p in missing_participants:
            league = self.get_participant_league(p)
            if league not in missing_preds:
                missing_preds[league] = []
            missing_preds[league].append(p)
        missing_preds_msg = "\n".join(f"__{Lang.lang(self, 'league_x', leag)}__: {', '.join(parts)}"
                                      for leag, parts in missing_preds.items())
        if missing_preds_msg:
            embed.add_field(name=Lang.lang(self, 'missing_predictions'), value=missing_preds_msg)
        else:
            embed.description = Lang.lang(self, 'no_predictions_missing')
        if no_preds_but_post:
            embed.add_field(name=Lang.lang(self, 'no_preds_but_post'), value=", ".join(no_preds_but_post), inline=False)

        for league_participants in participants:
            for p in league_participants:
                if p in found_users:
                    found_users.remove(p)
        if found_users:
            embed.add_field(name=Lang.lang(self, 'unknown_users'), value=", ".join(found_users), inline=False)

        await ctx.send(embed=embed)

    @cmd_spaetzle.command(name="rawpost")
    async def cmd_spaetzle_rawpost(self, ctx, participant: str):
        forumposts = Storage().get(self, container='forumposts')
        found: List[Embed] = []
        for post_id, post in forumposts['posts'].items():
            if participant.lower() not in post['user'].lower():
                continue
            stripped_content = [x for x in post['content'] if x.strip()]
            embed = Embed(description="\n".join(stripped_content[:15]),
                          timestamp=datetime.strptime(post['time'], "%d.%m.%Y - %H:%M Uhr"))
            embed.set_author(name=f"{post_id} | {post['user']}", url=f"https://www.transfermarkt.de{post['link']}")
            if len(stripped_content) > 15:
                embed.set_footer(text=Lang.lang(self, 'x_more_lines', len(stripped_content) - 15))
            found.append(embed)
        await ctx.send(Lang.lang(self, 'rawpost_count', len(found)))
        for embed_page in paginate_embeds(found):
            await ctx.send(embeds=embed_page)

    @cmd_spaetzle.group(name="set")
    async def cmd_spaetzle_set(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            pass

    @cmd_spaetzle_set.command(name="matchday")
    async def cmd_spaetzle_set_matchday(self, ctx: Context, matchday: int):
        async def confirm(_b, _i):
            Storage().get(self)['matchday'] = matchday
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

        await ctx.send(embed=Embed(title=Lang.lang(self, 'matchday'), description=matchday),
                       view=SingleConfirmView(confirm, user_id=ctx.author.id, confirm_label=Lang.lang(self, 'confirm')))

    @cmd_spaetzle_set.command(name="participants")
    async def cmd_spaetzle_set_participants(self, ctx: Context, league: Literal[1, 2, 3, 4], *participants: str):
        async def confirm(_b, _i):
            Storage().get(self)['participants'][league - 1] = sorted(participants)
            Storage().save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)

        await ctx.send(embed=Embed(title=Lang.lang(self, 'participants_x', league),
                                   description=", ".join(sorted(participants))),
                       view=SingleConfirmView(confirm, user_id=ctx.author.id, confirm_label=Lang.lang(self, 'confirm')))
