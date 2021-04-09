from data import Config, Lang
from botutils.utils import paginate, add_reaction

baselang = {
    "invalid_key": "Invalid config key",
    "invalid_value": "Invalid value",
    "set_success": "Changed {} value from {} to {}",
    "set_success_default": "Changed {} value from {} to the default value {}"
}


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

    def get_config(self, key):
        return Config.get(self.plugin).get(key, self.base_config[key][1])

    async def send(self, ctx, key, *args):
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

    async def set(self, ctx, key, value=None):
        """
        Sets the config value with the key `key` to `value` and sends an error/success report to ctx.

        :param ctx: Context
        :param key: Config key from whitelist
        :param value: Config value. If None, default value is set.
        """
        if key not in self.base_config:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.send(ctx, "invalid_key")
            return

        successlang = "set_success"
        if value is None:
            successlang = "set_success_default"
            value = self.base_config[key][1]
        else:
            try:
                value = self.base_config[key][0](value)
            except (TypeError, ValueError):
                await add_reaction(ctx.message, Lang.CMDERROR)
                await self.send(ctx, "invalid_value")
                return
        oldval = self.get_config(key)
        Config.get(self.plugin)[key] = value
        Config.save(self.plugin)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await self.send(ctx, successlang, key, oldval, value)
