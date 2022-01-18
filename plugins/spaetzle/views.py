from datetime import datetime
from typing import Coroutine, Callable

from nextcord import ui, Interaction, ButtonStyle

from base.data import Lang, Config


class ConfirmButton(ui.Button):
    def __init__(self, plugin, cb: Callable[[Interaction], Coroutine]):
        super().__init__(label=Lang.lang(plugin, 'confirm'), style=ButtonStyle.green)
        self.cb = cb

    async def callback(self, interaction: Interaction):
        await self.cb(interaction)
        await interaction.message.edit(view=None)
        await interaction.message.add_reaction(Lang.CMDSUCCESS)


class SetupMatchesConfirmation(ui.View):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.add_item(ConfirmButton(plugin, self.confirm))

    async def confirm(self, interaction: Interaction):
        time_cells = []
        team_cells = []
        match_cells = []
        matchday = interaction.message.embeds[0].title.split(" ")[-1]
        for row in interaction.message.embeds[0].description.split("\n"):
            dt, teams = row.split(" | ")
            kickoff_time = datetime.strptime(dt, "%a. %d.%m.%Y, %H:%M Uhr")
            home, away = teams.split(" - ")
            match = "{} - {}".format(Config().bot.liveticker.teamname_converter.get(home).abbr,
                                     Config().bot.liveticker.teamname_converter.get(away).abbr)
            time_cells.extend([kickoff_time.strftime("%d.%m.%Y %H:%M"), None])
            team_cells.extend([home, away])
            match_cells.extend([match, None])
        self.plugin.get_api_client().update(f"'ST {matchday}'!{Config().get(self.plugin)['ranges']['matches']}",
                                            [time_cells, team_cells, match_cells], raw=False)