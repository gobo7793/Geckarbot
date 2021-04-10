from enum import Enum

from data import Config, Lang
from botutils.utils import paginate, add_reaction

baselang = {
    "invalid_key": "Invalid config key",
    "invalid_value": "Invalid value",
    "set_success": "Changed {} value from {} to {}",
    "set_success_default": "Changed {} value from {} to the default value {}"
}


class Result(Enum):
    NEWVAL = 0
    DEFAULT = 1
    TOGGLE = 2


class ConfigSetter:
    """
    Handler for config setter commands for a simple key-value config.
    """
    def __init__(self, plugin, whitelist, desc=None, lang=None):
        """

        :param plugin: Plugin reference
        :param whitelist: dict that maps value information to config keys. Format:
            {key: [type, default_value]} ; e.g. {"limit": [int, 5]}
            type is a callable that converts strings to the respective type.
        :param desc: dict that maps descriptions to config keys. Desriptions are optional. Example:
            {"limit": "API request limit"}
        :param lang: dict to replace message strings; maps baselang keys to Lang.lang keys of the plugin. Set values
            to `None` to suppress the message entirely. Example:
            {"invalid_key": "config_invalid_key", "set_success": None}
        """
        self.plugin = plugin
        self.base_config = whitelist
        self.desc = desc if desc is not None else {}
        self.lang = lang if lang is not None else {}
        self.switches = []

    def add_switch(self, keys):
        """
        Adds a switch. A switch is a set of config keys with bool values where exactly one value is True at any time.
        If a second value is set to True, every other value is set to False. This only applies if the set / set_cmd
        methods are used.

        :param keys: List of keys that constitute the switch
        :raises RuntimeError: Raised if a switch condition is violated. These are:
            Key already present in another switch
            Value is not of type bool
            Default value of more than one key is True
            No key with default value True found
            Unknown key (key not in whitelist)
        """
        # check conditions
        for switch in self.switches:
            for key in keys:
                if key in switch:
                    raise RuntimeError("Key already present in another switch: {}".format(key))

        true_found = False
        for key in keys:
            try:
                valtype, valdefault = self.base_config[key]
            except KeyError:
                raise RuntimeError("Unknown key: {}".format(key))

            if valtype is not bool:
                raise RuntimeError("Type of {} value is not bool but {}".format(key, valtype))

            if valdefault:
                if true_found:
                    raise RuntimeError("Default value of more than one key is True")
                true_found = True
        if not true_found:
            raise RuntimeError("No key with default value True found")

        self.switches.append(keys.copy())

    def _process_switches(self, key, value):
        """
        Sets a boolean value and processes switches. Assumes correct typing in config and value.

        :param key: Config key 
        :param value: Config value
        """
        switch = None
        for el in self.switches:
            if key in el:
                switch = el
                break

        config = Config.get(self.plugin)
        oldval = config[key]
        config[key] = value
        if switch is None:
            return

        # Toggle to False => set default if necessary
        if not value:
            if not oldval:
                return

            # find default and set it
            for el in switch:
                if self.base_config[1]:
                    config[el] = True
            return

        # Toggle to True -> set everything else to False
        for el in switch:
            if el == key:
                continue
            config[el] = False

    def get_config(self, key):
        return Config.get(self.plugin).get(key, self.base_config[key][1])

    async def _send(self, ctx, key, *args):
        """
        Sends a lang string denoted by `key`.

        :param ctx: Context to send to
        :param key: lang key
        :param args: format args
        """
        try:
            msg = Lang.lang(self.plugin, self.lang[key], *args)
        except KeyError:
            msg = baselang[key].format(*args)

        if msg is not None:
            await ctx.send(msg)

    async def list(self, ctx):
        """
        Lists the current config values to ctx.

        :param ctx: Context
        """
        msg = []
        for el in self.base_config:
            msg.append("{}: {}".format(el, self.get_config(el)))
        for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

    def set(self, key, value=None):
        """
        Sets a value.

        :param key: Config key
        :param value: value to be set; None for default or bool toggle
        :return: Result instance
        :raises KeyError: Raised if `key` is not in the whitelist.
        :raises ValueError: Raised if `value` could not be typecasted correctly.
        """
        if key not in self.base_config:
            raise KeyError

        r = Result.NEWVAL
        if value is None:
            r = Result.DEFAULT
            valtype, value = self.base_config[key]
            if valtype is bool:
                self._process_switches(key, value)
                r = Result.TOGGLE
        else:
            try:
                value = self.base_config[key][0](value)
            except (TypeError, ValueError) as e:
                raise TypeError from e

        Config.get(self.plugin)[key] = value
        Config.save(self.plugin)
        return r

    async def set_cmd(self, ctx, key, value=None):
        """
        Sets the config value with the key `key` to `value` and sends an error/success report to ctx.

        :param ctx: Context
        :param key: Config key from whitelist
        :param value: Config value. If None, default value is set.
        """
        oldval = self.get_config(key)
        try:
            result = self.set(key, value)
        except KeyError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self._send(ctx, "invalid_key")
            return
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self._send(ctx, "invalid_value")
            return

        successlang = None
        if result in (Result.NEWVAL, Result.TOGGLE):
            successlang = "set_success"
        elif result == Result.DEFAULT:
            successlang = "set_success_default"
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await self._send(ctx, successlang, key, oldval, value)
