from datetime import datetime
from typing import Coroutine, Callable, Any, Union

from nextcord import ui, Interaction, ButtonStyle

from base.data import Lang, Config, Storage


class ConfirmButton(ui.Button):
    def __init__(self, plugin, user_id: int, cb: Callable[[Interaction, Any], Coroutine], *, label_key: str = 'confirm',
                 data: Any = None):
        super().__init__(label=Lang.lang(plugin, label_key), style=ButtonStyle.green)
        self.user_id = user_id
        self.cb = cb
        self.data = data

    async def callback(self, interaction: Interaction):
        if not interaction.user.id == self.user_id:
            return
        await self.cb(interaction, self.data)
        await interaction.message.edit(view=None)
        await interaction.message.add_reaction(Lang.CMDSUCCESS)


class SetupMatchesConfirmation(ui.View):
    def __init__(self, plugin, user_id: int):
        super().__init__()
        self.plugin = plugin
        self.add_item(ConfirmButton(plugin, user_id, self.confirm))

    async def confirm(self, interaction: Interaction, _):
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

class SetConfirmation(ui.View):
    def __init__(self, plugin, user_id: int, value: Any, show_config: bool, show_storage: bool):
        super().__init__()
        self.plugin = plugin
        self.value = value
        if show_config:
            self.add_item(ConfirmButton(plugin, user_id, self.confirm, label_key='confirm_config', data=Config))
        if show_storage:
            self.add_item(ConfirmButton(plugin, user_id, self.confirm, label_key='confirm_storage', data=Storage))

    async def confirm(self, interaction: Interaction, directory: Union[Config, Storage]):
        path = interaction.message.embeds[0].title.split(" > ")
        dir_ = directory.get(self.plugin)
        for step in path[:-1]:
            dir_ = dir_.get(step)
        dir_[path[-1]] = self.value
        directory.save(self.plugin)
