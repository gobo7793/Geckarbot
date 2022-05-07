from typing import Optional, Any, Callable, Coroutine, Iterable, Dict

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
    :param data: Opaque object
    """
    def __init__(self,
                 coro: Callable[['CoroButton', Interaction], Coroutine],
                 *,
                 style=ButtonStyle.secondary, label=None, disabled=False, custom_id=None, emoji=None, row=None,
                 data: Any = None):
        super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, emoji=emoji, row=row)
        self.coro = coro
        self.data = data

    async def callback(self, interaction: Interaction):
        await self.coro(self, interaction)


class CoroSelect(ui.Select):
    """
    Select/Dropdown menu with the ability to set the callback coroutine via a parameter.

    :param coro: Callback coroutine
    :param data: Opaque object
    :param options: A list of options that can be selected in this menu.
    :param placeholder: The placeholder text that is shown if nothing is selected, if any.
    :param min_values: The minimum number of items that must be chosen for this select menu. Defaults to 1 and must be
           between 1 and 25.
    :param max_values: The maximum number of items that must be chosen for this select menu. Defaults to 1 and must be
           between 1 and 25.
    :param disabled: Whether the select is disabled or not.
    :param row: The relative row this select menu belongs to. A Discord component can only have 5 rows. By default,
           items are arranged automatically into those 5 rows. If you'd like to control the relative positioning of the
           row then passing an index is advised. For example, row=1 will show up before row=2. Defaults to ``None``,
           which is automatic ordering. The row number must be between 0 and 4 (i.e. zero indexed).
    """
    def __init__(self,
                 coro: Callable[[ui.Select, Interaction], Coroutine],
                 options,
                 *,
                 placeholder=None, min_values=1, max_values=1, disabled=False, row=None, data: Any = None):
        super().__init__(placeholder=placeholder, min_values=min_values, max_values=max_values,
                         options=options, disabled=disabled, row=row)
        self.coro = coro
        self.data = data

    async def callback(self, interaction: Interaction):
        await self.coro(self, interaction)


class SingleItemView(ui.View):
    """
    View with a bunch of UI items

    :param item: Item to add to the view
    :param data: Opaque object
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If
           ``None`` then there is no timeout.
    """
    def __init__(self,
                 item: ui.Item,
                 *,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        self.data = data
        super().__init__(timeout=timeout)
        self.add_item(item)


class MultiItemView(ui.View):
    """
    View with a bunch of UI items

    :param items: Items to add to the view
    :param data: Opaque object
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If
           ``None`` then there is no timeout.
    """
    def __init__(self,
                 items: Iterable[ui.Item],
                 *,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        self.data = data
        super().__init__(timeout=timeout)
        for item in items:
            self.add_item(item)


class MultiConfirmView(MultiItemView):
    """
    Confirmation View with multiple options.

    :param buttons: Confirm options
    :param user_id: If set, buttons will only respond if pressed by the specified user. Otherwise, every user can
       execute the actions
    :param abort_button: Custom abort button
    :param disable_separately: If set to True, multiple options can be picked. Otherwise the view will disable
        itself after first entry
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If ``None``
       then there is no timeout.
    """
    def __init__(self,
                 buttons: Iterable[ui.Button],
                 *,
                 user_id: Optional[int] = None,
                 abort_button: Optional[ui.Button] = None,
                 disable_separately: bool = False,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        if abort_button:
            abort_button.style = ButtonStyle.red
        else:
            abort_button = ui.Button(label="X", style=ButtonStyle.red)
        for item in buttons:
            item.style = ButtonStyle.green
        self.disable_separately = disable_separately
        self.user_id = user_id
        self.coro_dict: Dict[ui.Button, Callable] = {}
        refactored_items = []
        for item in (*buttons, abort_button):
            if isinstance(item, CoroButton):
                self.coro_dict[item] = item.coro
                item.coro = self.execute_action
            else:
                item = CoroButton(self.execute_action, style=item.style, label=item.label, disabled=item.disabled,
                                  custom_id=item.custom_id, emoji=item.emoji, row=item.row)
            refactored_items.append(item)
        super().__init__(items=refactored_items, timeout=timeout, data=data)

    async def execute_action(self, button: ui.Button, interaction: Interaction):
        """Executes action originally assigned to button"""
        if self.user_id == interaction.user.id:
            if button in self.coro_dict:
                await self.coro_dict[button](button, interaction)
            await self.disable(button, interaction)

    async def disable(self, button: ui.Button, interaction: Interaction):
        """
        Disable pressed button (respectively all buttons if disable_separately is False or button is abort) and stop
        the view if nothing left.

        :param button: Pressed button
        :param interaction: Interaction object
        """
        button.disabled = True
        if button.style == ButtonStyle.red or not self.disable_separately:
            for item in self.children[:]:
                if not item.disabled:
                    self.remove_item(item)
        if all(item.disabled for item in self.children):
            self.stop()
        await interaction.message.edit(view=self)



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
    :param timeout: Timeout in seconds from last interaction with the UI before no longer accepting input. If ``None``
           then there is no timeout.
    """
    def __init__(self,
                 confirm_coro: Optional[Callable[[CoroButton, Interaction], Coroutine]] = None,
                 *,
                 confirm_label: str = "Confirm",
                 abort_label: str = "X",
                 abort_coro: Optional[Callable[[ui.Button, Interaction], Coroutine]] = None,
                 user_id: Optional[int] = None,
                 data: Any = None,
                 timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout, data=data, items=(
            CoroButton(label=confirm_label, coro=self.confirm, style=ButtonStyle.green, emoji=Lang.CMDSUCCESS),
            CoroButton(label=abort_label, coro=self.abort, style=ButtonStyle.red)
        ))
        self.abort_coro = abort_coro
        self.confirm_coro = confirm_coro
        self.user_id = user_id

    async def confirm(self, button: CoroButton, interaction: Interaction):
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
