from typing import Optional, Any, Callable, Coroutine, Iterable

from nextcord import ui, Interaction, ButtonStyle

from base.data import Lang


class CoroButton(ui.Button):
    """
    Button, but with the ability to set the callback coroutine via a parameter.

    :param coro: Callback coroutine
    :param style: The style of the button.
    :param label: The label of the button, if any.
    :param emoji: The emoji of the button, if available.
    :param disabled: Whether the button is disabled or not.
    :param custom_id: The ID of the button that gets received during an interaction.
    :param row: The relative row this button belongs to. A Discord component can only have 5 rows. By default, items
           are arranged automatically into those 5 rows. If you'd like to control the relative positioning of the
           row then passing an index is advised. For example, row=1 will show up before row=2. Defaults to ``None``,
           which is automatic ordering. The row number must be between 0 and 4 (i.e. zero indexed).
    """
    def __init__(self,
                 coro: Callable[[ui.Button, Interaction], Coroutine],
                 *,
                 style=ButtonStyle.secondary, label=None, disabled=False, custom_id=None, emoji=None, row=None):
        super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, emoji=emoji, row=row)
        self.coro = coro

    async def callback(self, interaction: Interaction):
        await self.coro(self, interaction)


class SingleItemView(ui.View):
    """
    View with a bunch of UI items

    :param item: Item to add to the view
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If
           ``None`` then there is no timeout.
    """
    def __init__(self,
                 item: ui.Item,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        self.add_item(item)


class MultiItemView(ui.View):
    """
    View with a bunch of UI items

    :param items: Items to add to the view
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If
           ``None`` then there is no timeout.
    """
    def __init__(self,
                 items: Iterable[ui.Item],
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        for item in items:
            self.add_item(item)


class SingleConfirmView(MultiItemView):
    """
    View with one button to confirm an input and an abort button. Buttons only react to the specified user and disable
    itself after pressing, only showing the pressed button afterwards.

    :param user_id: If set, buttons will only respond if pressed by the specified user. Otherwise, every user can
           execute the actions
    :param confirm_label: Label of the confirm button
    :param abort_label: Label of the abort button
    :param confirm_coro: Coroutine to execute if specified user pressed the confirm button
    :param abort_coro: Coroutine to execute if specified user pressed the abort button
    :param data: Opaque object that is set to self.data
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If ``None``
           then there is no timeout.
    """
    def __init__(self,
                 confirm_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 *,
                 confirm_label: str = "Confirm",
                 abort_label: str = "X",
                 abort_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 user_id: Optional[int] = None,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout, items=(
            CoroButton(label=confirm_label, coro=self.confirm, style=ButtonStyle.green, emoji=Lang.CMDSUCCESS),
            CoroButton(label=abort_label, coro=self.abort, style=ButtonStyle.red)
        ))
        self.abort_coro = abort_coro
        self.confirm_coro = confirm_coro
        self.data = data
        self.user_id = user_id

    async def confirm(self, button: ui.Button, interaction: Interaction):
        """
        Action to perform when confirm button is pressed

        :param button: Pressed button
        :param interaction: Interaction object
        """
        if self.user_id == interaction.user.id:
            if self.confirm_coro:
                await self.confirm_coro(button, interaction)
            await self.disable(button, interaction)

    async def abort(self, button: ui.Button, interaction: Interaction):
        """
        Action to perform when abort button is pressed

        :param button: Pressed button
        :param interaction: Interaction object
        """
        if self.user_id == interaction.user.id:
            if self.abort_coro:
                await self.abort_coro(button, interaction)
            await self.disable(button, interaction)

    async def disable(self, button: ui.Button, interaction: Interaction):
        """
        Remove all other buttons, disable pressed button und stop the view

        :param button: Pressed button
        :param interaction: Interaction object
        """
        self.clear_items()
        button.disabled = True
        self.add_item(button)
        await interaction.message.edit(view=self)
        self.stop()
