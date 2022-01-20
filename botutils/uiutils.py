from typing import Optional, Any, Callable, Coroutine

from nextcord import ui, Interaction, ButtonStyle

from base.configurable import Configurable
from base.data import Lang


class SingleConfirmView(ui.View):
    class ConfirmButton(ui.Button):
        def __init__(self, label: str, coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None):
            super().__init__(style=ButtonStyle.green, label=label)
            self.coro = coro

        async def callback(self, interaction: Interaction):
            if self.view.user_id == interaction.user.id:
                if self.coro:
                    await self.coro(self, interaction)
                self.view.stop()

    class AbortButton(ui.Button):
        def __init__(self, coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None):
            super().__init__(style=ButtonStyle.red, label="X")
            self.coro = coro

        async def callback(self, interaction: Interaction):
            if self.view.user_id == interaction.user.id:
                if self.coro:
                    await self.coro(self, interaction)
                self.view.stop()


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
        self.user_id = user_id
        self.data = data
        self.add_item(self.ConfirmButton(label=Lang.lang(plugin, lang_key), coro=confirm_coro))
        self.add_item(self.AbortButton(coro=abort_coro))

    def stop(self):
        for item in self.children:
            item.disabled = True
        super().stop()
