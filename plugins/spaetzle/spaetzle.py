import json
import logging
from json import JSONDecodeError

from nextcord import Embed
from nextcord.ext import commands
from nextcord.ext.commands import Context

from Geckarbot import BasePlugin
from base.data import Config, Lang, Storage
from botutils import sheetsclient
from botutils.utils import helpstring_helper
from plugins.spaetzle import views
from services.helpsys import DefaultCategories
from services.liveticker import LeagueRegistrationOLDB


class Plugin(BasePlugin, name="Spaetzle-Tippspiel"):
    """Plugin for the Spaetzle(s)-Tippspiel"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, category=DefaultCategories.SPORT)

        self.logger = logging.getLogger(__name__)

    def default_config(self, container=None):
        return {
            '_config_version': 1,
            'ranges': {
                'matches': "Q2:AH4"
            },
            'spaetzledoc_id': "1eUCYWLw09CBzxJj3Zx-t8ssVwdqsjRgzzj37paPtZIA",
        }

    def default_storage(self, container=None):
        return {
            '_storage_version': 1,
            'matchday': 0
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
        matchday = Storage().get(self)['matchday']
        match_list = await LeagueRegistrationOLDB.get_matches_by_matchday(league="bl1", matchday=matchday)
        await ctx.send(embed=Embed(title=Lang.lang(self, 'title_matchday', matchday),
                                   description="\n".join(m.display_short() for m in match_list)),
                       view=views.SetupMatchesConfirmation(self, ctx.author.id))

    @cmd_spaetzle_setup.command(name="duels")
    async def cmd_spaetzle_setup_duels(self, ctx: Context):
        pass

    @cmd_spaetzle.command(name="set")
    async def cmd_spaetzle_set(self, ctx: Context, *, args: str):
        class Missing:
            @staticmethod
            def get(*_):
                return Missing()

        path, *value_list = args.split(" | ")
        steps = path.split(" ")
        if value_list:
            value = " | ".join(value_list)
        else:
            value = " ".join(steps[-1:])
            steps = steps[:-1]
        if not steps:
            await ctx.send(Lang.lang(self, 'set_err_split'))
            return

        try:
            value_json = json.loads(value)
        except JSONDecodeError:
            await ctx.send(Lang.lang(self, 'set_err_value'))
            return

        config = Config().get(self)
        storage = Storage().get(self)
        for step in steps:
            if step.startswith("_"):
                await ctx.send(Lang.lang(self, 'set_err_private'))
                return
            try:
                config = config.get(step, Missing())
            except (KeyError, AttributeError):
                config = Missing()
            try:
                storage = storage.get(step, Missing())
            except (KeyError, AttributeError):
                storage = Missing()
        embed = Embed(title=" > ".join(steps))
        if not isinstance(config, Missing):
            embed.add_field(name="Config", value=config)
        if not isinstance(storage, Missing):
            embed.add_field(name="Storage", value=storage)
        if len(embed.fields) < 1:
            await ctx.send(Lang.lang(self, 'set_err_no_path'))
            return
        embed.add_field(name=Lang.lang(self, 'new_value'), value=value_json)
        await ctx.send(embed=embed, view=views.SetConfirmation(self, user_id=ctx.author.id, value=value_json,
                                                               show_config=not isinstance(config, Missing),
                                                               show_storage=not isinstance(storage, Missing)))
