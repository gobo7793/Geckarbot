import logging
from enum import Enum

from discord import TextChannel, Member, User, Role
from discord.ext.commands.converter import TextChannelConverter, UserConverter, MemberConverter, RoleConverter
from discord.ext.commands.errors import ChannelNotFound, UserNotFound, MemberNotFound, RoleNotFound

from data import Config, Lang
from botutils.utils import paginate, add_reaction

baselang = {
    "invalid_key": "Invalid config key",
    "invalid_value": "Invalid value",
    "set_success": "Changed {} value from {} to {}",
    "set_success_default": "Changed {} value from {} to the default value {}"
}


convmap = {
    TextChannel: TextChannelConverter,
    User: UserConverter,
    Member: MemberConverter,
    Role: RoleConverter,
}


class InvalidKey(Exception):
    pass


class InvalidValue(Exception):
    pass


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
            Discord types are supported and converted to their respective ids.
        :param desc: dict that maps descriptions to config keys. Desriptions are optional. Example:
            {"limit": "API request limit"}
        :param lang: dict to replace message strings; maps baselang keys to Lang.lang keys of the plugin. Set values
            to `None` to suppress the message entirely. Example:
            {"invalid_key": "config_invalid_key", "set_success": None}
        """
        self.logger = logging.getLogger(__name__)
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
            except KeyError as e:
                raise RuntimeError("Unknown key: {}".format(key)) from e

            if valtype is not bool:
                raise RuntimeError("Type of {} value is not bool but {}".format(key, valtype))

            if valdefault:
                if true_found:
                    raise RuntimeError("Default value of more than one key is True")
                true_found = True
        if not true_found:
            raise RuntimeError("No key with default value True found")

        self.switches.append(tuple(keys))

    @staticmethod
    def parse_bool_str(s):
        """
        Accepts strings like "True" or "false" and returns the corresponding boolean value.

        :param s: input string
        :return: bool that corresponds to the semantic understanding of s
        :raises ValueError: Raised if the resulting boolean value could not be determined.
        """
        c = s.lower().strip()
        if c == "true":
            return True
        if c == "false":
            return False
        raise ValueError("Could not parse {} to a boolean value".format(s))

    def _process_switches(self, key, value):
        """
        Sets a boolean value and processes switches. Assumes correct typing in config and value. Does not call save.

        :param key: Config key
        :param value: Config value
        """
        switch = None
        for el in self.switches:
            if key in el:
                switch = el
                break

        config = Config.get(self.plugin)
        oldval = self.get_config(key)
        config[key] = value
        if switch is None:
            return

        # Toggle to False => set default if necessary
        if not value:
            # new value == old value
            if not oldval:
                return

            # find default and set it
            for el in switch:
                if self.base_config[el][1]:
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
        Sends the lang string that is identified by `key`.

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

    def _format_entry(self, key):
        msg = "{}: {}".format(key, self.get_config(key))
        desc = False
        if key in self.desc:
            msg = "{}\n  {}".format(msg, self.desc[key])
            desc = True
        return msg, desc

    async def list(self, ctx):
        """
        Lists the current config values to ctx.

        :param ctx: Context
        """
        self.logger.debug("Listing config of plugin %s", self.plugin.get_name())
        done = {key: False for key in self.base_config}

        # Process switches
        switches = []
        for i in range(len(self.switches)):
            switch = self.switches[i]
            last = i + 1 == len(self.switches)

            for key in switch:
                msg, _ = self._format_entry(key)
                switches.append(msg)
                done[key] = True
            if not last:
                switches.append("")

        # Process the rest
        with_desc = []
        without_desc = []
        for key in done:
            if done[key]:
                continue
            done[key] = True

            msg, desc = self._format_entry(key)
            if desc:
                with_desc.append(msg)
            else:
                without_desc.append(msg)

        # Dividers
        if with_desc and switches:
            switches.insert(0, "")
        if (switches or with_desc) and without_desc:
            without_desc.insert(0, "")

        for msg in paginate(with_desc + switches + without_desc, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

    async def set(self, key, value=None, ctx=None) -> Result:
        """
        Sets a value.

        :param key: Config key
        :param value: value to be set; None for default or bool toggle
        :param ctx: Context, only needed for discord types (such as TextChannel or User)
        :return: Result instance
        :raises InvalidKey: Raised if `key` is not in the whitelist.
        :raises InvalidValue: Raised if `value` could not be typecasted correctly.
        :raises RuntimeError: Raised if discord types are set and ctx is None
        """
        if key not in self.base_config:
            raise InvalidKey
        valtype, default = self.base_config[key]
        r = Result.NEWVAL

        # Convert discord types
        if value is None and valtype in (TextChannel, User, Member, Role):
            r = Result.DEFAULT
            Config.get(self.plugin)[key] = default

        elif valtype in (TextChannel, User, Member, Role):
            if ctx is None:
                raise RuntimeError("Cannot convert discord types without ctx")

            try:
                value = await convmap[valtype]().convert(ctx, value)
            except (ChannelNotFound, UserNotFound, MemberNotFound, RoleNotFound) as e:
                raise InvalidValue from e

            Config.get(self.plugin)[key] = value.id

        # Special handling of bools for switch reasons
        elif valtype is bool:
            if value is None:
                r = Result.TOGGLE
                value = default
            else:
                try:
                    value = self.parse_bool_str(value)
                except ValueError as e:
                    raise InvalidValue from e

            self._process_switches(key, value)

        else:
            if value is None:
                r = Result.DEFAULT
                value = default
            else:
                try:
                    value = valtype(value)
                except (TypeError, ValueError) as e:
                    raise InvalidValue from e
            Config.get(self.plugin)[key] = value

        self.logger.debug("Plugin %s: setting %s to %s", self.plugin.get_name(), key, str(value))
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
            result = await self.set(key, value=value, ctx=ctx)
        except InvalidKey:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self._send(ctx, "invalid_key")
            return
        except InvalidValue:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self._send(ctx, "invalid_value")
            return

        successlang = None
        if result in (Result.NEWVAL, Result.TOGGLE):
            successlang = "set_success"
        elif result == Result.DEFAULT:
            successlang = "set_success_default"
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await self._send(ctx, successlang, key, oldval, self.get_config(key))
