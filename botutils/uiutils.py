from typing import Optional, Any, Callable, Coroutine

from nextcord import ui, Interaction, ButtonStyle

from base.configurable import Configurable
from base.data import Lang


class CoroButton(ui.Button):
    def __init__(self,
                 coro: Callable[[ui.Button, Interaction], Coroutine],
                 *,
                 style=ButtonStyle.secondary, label=None, disabled=False, custom_id=None, emoji=None, row=None):
        super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, emoji=emoji, row=row)
        self.coro = coro

    async def callback(self, interaction: Interaction):
        await self.coro(self, interaction)


class SingleButtonView(ui.View):
    def __init__(self,
                 label: Optional[str] = None,
                 coro: Callable[[ui.Button, Interaction], Coroutine] = None,
                 style=ButtonStyle.secondary,
                 disabled=False,
                 custom_id=None,
                 emoji=None,
                 row=None,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        if coro:
            self.add_item(CoroButton(coro=coro, label=label, style=style, disabled=disabled, custom_id=custom_id,
                                     emoji=emoji, row=row))
        else:
            self.add_item(ui.Button(label=label, style=style, disabled=disabled, custom_id=custom_id, emoji=emoji,
                                    row=row))


class SingleConfirmView(ui.View):
    async def confirm(self, button: ui.Button, interaction: Interaction):
        if self.user_id == interaction.user.id:
            if self.confirm_coro:
                await self.confirm_coro(button, interaction)
            await self.disable(button, interaction)

    async def abort(self, button: ui.Button, interaction: Interaction):
        if self.user_id == interaction.user.id:
            if self.abort_coro:
                await self.abort_coro(button, interaction)
            await self.disable(button, interaction)

    def __init__(self,
                 plugin: Configurable,
                 lang_key: str = 'confirm',
                 *,
                 user_id: Optional[int] = None,
                 confirm_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 abort_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        self.abort_coro = abort_coro
        self.confirm_coro = confirm_coro
        self.data = data
        self.user_id = user_id
        self.add_item(CoroButton(label=Lang.lang(plugin, lang_key), coro=self.confirm, style=ButtonStyle.green))
        self.add_item(CoroButton(label='X', coro=self.abort, style=ButtonStyle.red))

    async def disable(self, button: ui.Button, interaction: Interaction):
        self.clear_items()
        button.disabled = True
        self.add_item(button)
        await interaction.message.edit(view=self)
        super().stop()
