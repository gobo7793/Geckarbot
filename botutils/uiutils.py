from typing import Optional, Any, Callable, Coroutine, Iterable

from nextcord import ui, Interaction, ButtonStyle

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
                 button: ui.Button,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        self.add_item(button)


class MultiButtonView(ui.View):
    def __init__(self,
                 buttons: Iterable[ui.Button],
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        for item in buttons:
            self.add_item(item)


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
                 confirm_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 *,
                 confirm_label: str = "Confirm",
                 abort_label: str = "X",
                 abort_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 user_id: Optional[int] = None,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        self.abort_coro = abort_coro
        self.confirm_coro = confirm_coro
        self.data = data
        self.user_id = user_id
        self.add_item(CoroButton(label=confirm_label, coro=self.confirm, style=ButtonStyle.green,
                                 emoji=Lang.CMDSUCCESS))
        self.add_item(CoroButton(label=abort_label, coro=self.abort, style=ButtonStyle.red))

    async def disable(self, button: ui.Button, interaction: Interaction):
        self.clear_items()
        button.disabled = True
        self.add_item(button)
        await interaction.message.edit(view=self)
        super().stop()
