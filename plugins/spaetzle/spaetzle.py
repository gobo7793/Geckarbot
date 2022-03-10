import logging
import re
from datetime import datetime
from typing import Literal, List, Optional
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from nextcord import Embed, Interaction
from nextcord.ext import commands
from nextcord.ext.commands import Context

from Geckarbot import BasePlugin
from base.data import Config, Lang, Storage
from botutils import sheetsclient, restclient
from botutils.sheetsclient import CellRange
from botutils.uiutils import SingleConfirmView
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
        SpaetzleUtils.__init__(self, self.bot)

        self.logger = logging.getLogger(__name__)

    def default_config(self, container=None):
        return {
            '_config_version': 1,
            'ranges': {
                'duel_columns': "B:D",
                'league_rows': ["6:23", "25:42", "44:61", "63:80"],
                'matches': "Q2:AH4",
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
            'participants': {[], [], [], []},
            'predictions_thread': ""
        }

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

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
        await ctx.send(embed=Embed(title=Lang.lang(self, 'title_matchday', matchday),
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

        async def insert_to_spreadsheet(_b, interaction: Interaction):
            embed_fields = interaction.message.embeds[0].fields
            data_dict = {}
            for j in range(4):
                duels_rows = []
                for row in embed_fields[j].value.split("\n"):
                    for p in row.split(" - "):
                        duels_rows.append([None, p, f"={self.get_participant_point_cell(p, league=j + 1)}"])
                range_name = CellRange.from_a1(Config().get(self)['ranges']['league_rows'][j]).overlay_range(
                    CellRange.from_a1(Config().get(self)['ranges']['duel_columns'])).rangename()
                data_dict[f"ST {Storage().get(self)['matchday']}!{range_name}"] = duels_rows
            self.get_api_client().update_multiple(data_dict, raw=False)

        embed = Embed(title=Lang.lang(self, 'duels_mx', Storage().get(self)['matchday']))
        participants = Storage().get(self)['participants']
        for i in range(len(participants)):
            schedule = calculate_schedule(participants[i])
            embed.add_field(name=Lang.lang(self, 'league_x', i + 1), value="\n".join(f"{x} - {y}" for x, y in schedule))
        await ctx.send(embed=embed, view=SingleConfirmView(insert_to_spreadsheet, user_id=ctx.author.id,
                                                           confirm_label=Lang.lang(self, 'confirm')))

    @cmd_spaetzle.command(name="scrape")
    async def cmd_spaetzle_scrape(self, ctx: Context, url: str = None):
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
                            'content': re.sub(r'(?:(?!\n)\s){2,}', ' ', p_data.text.replace('\u2013', '-')).split("\n")
                        }

                await botmessage.edit(content="{}\n{}".format(botmessage.content,
                                                              Lang.lang(self, 'scrape_intermediate', len(post_list))))
                next_page = soup.find_all('li', 'tm-pagination__list-item--icon-next-page')
                if next_page and next_page[0].a:
                    url = urljoin(Storage().get(self)['predictions_thread'], next_page[0].a['href'])
                else:
                    await ctx.send(Lang.lang(self, 'scrape_end'))
                    break

            Storage().set(self, {'init': init_content, 'posts': post_list, 'url': original_url}, container='forumposts')
            Storage().save(self, container='forumposts')
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spaetzle.command(name="extract")
    async def cmd_spaetzle_extract(self, ctx: Context):
        forumposts = Storage().get(self, container='forumposts')
        ...

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
            embed.set_author(name=f"{post_id} | {post['user']}", url=forumposts['url'])
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
