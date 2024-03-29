from enum import Enum
import logging
from typing import List, Tuple, Optional, Union

from nextcord.ext import commands
from nextcord.ext.commands import Context, Command

from base.configurable import BaseSubsystem, NotFound, BasePlugin, ConfigurableType
from base.data import Lang, Config
from botutils.utils import add_reaction, get_plugin_by_cmd, helpstring_helper
from botutils.stringutils import paginate


class CategoryNotFound(Exception):
    pass


class CategoryExists(Exception):
    pass


class DefaultCategories(Enum):
    """
    Default categories that plugins can be sorted into if desirable.
    """
    UTILS = 0
    GAMES = 1
    SPORT = 2
    MISC = 3
    USER = 4
    MOD = 5
    ADMIN = 6


class CategoryOrder(Enum):
    """
    Classes that help categories are ordered by when listing them.
    """
    FIRST = 0
    MIDDLE = 1
    LAST = 2


class HelpCog(BasePlugin):
    """
    Cog for help commands
    """
    def __init__(self):
        self.bot = Config().bot
        super().__init__()
        self.category = HelpCategory(self.bot, Lang.lang(self, "self_category_name"),
                                     desc=Lang.lang(self, "cat_desc_help"))
        self.category.add_plugin(self)

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    @commands.group(name="help", invoke_without_command=True)
    async def cmd_help(self, ctx, *args):
        await self.bot.helpsys.helpcmd(ctx, *args)

    @commands.command(name="usage", hidden=True)
    async def cmd_usage(self, ctx, *args):
        await self.bot.helpsys.usagecmd(ctx, *args)

    @cmd_help.command(name="all")
    async def cmd_all(self, ctx, *args):
        await self.bot.helpsys.listcmd(ctx, *args)

    @cmd_help.command(name="hidden", hidden=True)
    async def cmd_hidden(self, ctx, *args):
        await self.bot.helpsys.hiddencmd(ctx, *args)

    @commands.command(name="locate")
    async def locatecmd(self, ctx, *args):
        await self.bot.helpsys.locatecmd(ctx, *args)


class HelpCategory:
    """
    Represents a help category.
    """
    def __init__(self, bot, name, desc="", order=CategoryOrder.MIDDLE, defaultcat=False):
        self._name = name[0].upper() + name[1:]
        self.description = desc
        self.plugins = []  # plugins that are added to this cat
        self.standalone_commands = []  # separate commands that are added to this cat
        self.blacklist = []  # commands that are removed from this cat
        self.order = order
        self.bot = bot
        self.default = defaultcat

    def __str__(self):
        return "<help.HelpCategory; name: {}, order: {}>".format(self.name, self.order)

    def __len__(self):
        r = 0
        for el in self.command_list():
            if not el.hidden:
                r += 1
        return r

    @property
    def name(self):
        return self._name

    def match_name(self, name: str) -> bool:
        """
        :return: `True` if `name` is a valid name for this category, `False` otherwise.
        """
        if name.lower() == self.name.lower():
            return True
        return False

    def is_empty(self) -> bool:
        """
        :return: True if this HelpCategory does not contain any plugins, False otherwise.
        """
        return len(self.plugins) == 0 and len(self.standalone_commands) == 0

    def add_plugin(self, plugin: BasePlugin):
        """
        Adds a plugin to this HelpCategory.

        :param plugin: BasePlugin instance to be added to the category
        """
        self.plugins.append(plugin)

    def remove_plugin(self, plugin: BasePlugin):
        """
        Removes a plugin from this HelpCategory.

        :param plugin: BasePlugin instance to be added to the category
        """
        if plugin in self.plugins:
            self.plugins.remove(plugin)

        if self.is_empty() and not self.default:
            try:
                self.bot.helpsys.deregister_category(self)
            except CategoryNotFound:
                pass

    def add_command(self, command: Command):
        """
        Adds a standalone command to this HelpCategory.

        :param command: Command that is to be added to the category
        """
        while command in self.blacklist:
            self.blacklist.remove(command)
        self.standalone_commands.append(command)

    def remove_command(self, command: Command):
        """
        Removes a standalone command from this HelpCategory.

        :param command: Command that is to be removed from the category
        """
        while command in self.standalone_commands:
            self.standalone_commands.remove(command)
        self.blacklist.append(command)

    def single_line(self) -> str:
        """
        :return: One-line string that represents this HelpCategory.
        """
        r = self.name
        if self.description:
            r = "{} - {}".format(r, self.description)
        return "{} ({})".format(r, len(self))

    def command_list(self):
        r = []
        for el in self.plugins:
            for cmd in el.get_commands():
                if cmd not in self.blacklist:
                    r.append(cmd)
        return r + self.standalone_commands

    def sort_commands(self, ctx, cmds):
        # pylint: disable=no-self-use
        return sorted(cmds, key=lambda x: x.name)

    def format_commands(self, ctx) -> List[str]:
        """
        :return: Message list with all commands that this category contains to be consumed by paginate().
        """
        r = []
        cmds = self.sort_commands(ctx, self.command_list())
        for command in cmds:
            if not command.hidden:
                r.append("  {}".format(self.bot.helpsys.format_command_help_line(command.cog, command)))
        return r

    async def send_category_help(self, ctx):
        """
        Sends a help message for this category.

        :param ctx: Context that the help message is to be sent to.
        """
        msg = self.format_commands(ctx)
        for msg in paginate(msg,
                            prefix=Lang.lang(self.bot.helpsys, "help_category_prefix", self.name) + "\n",
                            msg_prefix="```",
                            msg_suffix="```"):
            await ctx.send(msg)


Category = Union[DefaultCategories, HelpCategory]


class GeckiHelp(BaseSubsystem):
    """
    Subsystem that handles the bot's `!help` command.
    """
    def __init__(self):
        self.bot = Config().bot
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.default_categories = {
            DefaultCategories.UTILS: HelpCategory(self.bot, Lang.lang(self, "default_category_utils"),
                                                  desc=Lang.lang(self, "cat_desc_utils"),
                                                  order=CategoryOrder.FIRST, defaultcat=True),
            DefaultCategories.GAMES: HelpCategory(self.bot, Lang.lang(self, "default_category_games"),
                                                  desc=Lang.lang(self, "cat_desc_games"),
                                                  defaultcat=True),
            DefaultCategories.SPORT: HelpCategory(self.bot, Lang.lang(self, "default_category_sport"),
                                                  desc=Lang.lang(self, "cat_desc_sport"),
                                                  defaultcat=True),
            DefaultCategories.MISC: HelpCategory(self.bot, Lang.lang(self, "default_category_misc"),
                                                 desc=Lang.lang(self, "cat_desc_misc"),
                                                 order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.USER: HelpCategory(self.bot, Lang.lang(self, "default_category_user"),
                                                 desc=Lang.lang(self, "cat_desc_user"),
                                                 order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.MOD: HelpCategory(self.bot, Lang.lang(self, "default_category_mod"),
                                                desc=Lang.lang(self, "cat_desc_mod"),
                                                order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.ADMIN: HelpCategory(self.bot, Lang.lang(self, "default_category_admin"),
                                                  desc=Lang.lang(self, "cat_desc_admin"),
                                                  order=CategoryOrder.LAST, defaultcat=True),
        }

        self._categories = list(self.default_categories.values())

        # Setup help cmd
        self.bot.remove_command("help")
        self.cog = HelpCog()
        self.bot.add_cog(self.cog)
        self.register_category(self.cog.category)

    ######
    # Housekeeping methods
    ######
    def default_category(self, const: DefaultCategories) -> HelpCategory:
        """
        :param const: One out of DefaultCategories
        :return: Corresponding registered category
        """
        return self.default_categories[const]

    def category(self, name: str) -> Optional[HelpCategory]:
        """
        :param name: Category name
        :return: Returns the HelpCategory with name `name`. None if no such HelpCategory is found.
        """
        for cat in self._categories:
            if cat.match_name(name):
                return cat
        return None

    def categories_by_plugin(self, plugin: BasePlugin) -> List[HelpCategory]:
        """
        :param plugin: Plugin
        :return: List of HelpCategory objects that contain `plugin`
        """
        r = []
        for cat in self._categories:
            if plugin in cat.plugins:
                r.append(cat)
        return r

    def register_category_by_name(self, name: str, description: str = "") -> HelpCategory:
        """
        Creates and registers a help category by name only.

        :param name: Help category name
        :param description: Help category description
        :return: HelpCategory that was created and registered
        """
        cat = self.category(name)
        if cat is None:
            cat = HelpCategory(self.bot, name, desc=description)
            self.register_category(cat)
        return cat

    def register_category(self, category: Category) -> HelpCategory:
        """
        Registers a category with Help. If a DefaultCategory is parsed, nothing is registered,
        but the corresponding registered HelpCategory is returned.

        :param category: HelpCategory instance or DefaultCategory instance
        :return: The registered HelpCategory
        :raises CategoryExists: Raised if `category` is already registered.
        """
        # Catch default category
        if isinstance(category, DefaultCategories):
            return self.default_category(category)

        exists = self.category(category.name)
        if exists:
            raise CategoryExists(category.name)

        category.bot = self.bot
        self._categories.append(category)
        return category

    def deregister_category(self, category: Category):
        """
        Deregisters a help category. If a DefaultCategory is parsed, nothing is deregistered.

        :param category: HelpCategory instance or DefaultCategory instance
        :raises CategoryNotFound: Raised if `category` was not registered.
        """
        if isinstance(category, DefaultCategories):
            return

        exists = self.category(category.name)
        if not exists:
            raise CategoryNotFound(category.name)

        self._categories.remove(category)

    def purge_plugin(self, plugin: BasePlugin):
        """
        Removes a plugin and its commands from all help categories.

        :param plugin: Plugin to remove
        """
        cats = self.categories_by_plugin(plugin)
        for cat in cats:
            cat.remove_plugin(plugin)
        for cmd in plugin.get_commands():
            for cat in self._categories:
                cat.remove_command(cmd)

    #######
    # Parsing methods
    #######
    def find_command(self, args) -> Tuple[Optional[BasePlugin], Optional[commands.Command]]:
        """
        Finds the command that is resembled by `args`.

        :return: `(plugin, command)`.
            `plugin` is the plugin where the found command `command` is registered in.
            If nothing is found, returns `(None, None)`.
        """
        # pylint: disable=unnecessary-comprehension
        plugins = [self.cog] + [el for el in self.bot.plugin_objects(plugins_only=True)]

        # lower()
        args = [el.lower() for el in args]

        # find plugin
        assert len(args) > 0
        plugin = None
        cmd = None
        for el in plugins:
            for command in el.get_commands():
                if command.name == args[0] or args[0] in command.aliases:
                    cmd = command
                    plugin = el
                    break
        if plugin is None:
            return None, None

        # find cmd
        for arg in args[1:]:
            if isinstance(cmd, commands.Group):
                cmd = cmd.get_command(arg)
            else:
                return None, None
        if cmd is not None:
            return plugin, cmd
        return None, None

    def all_commands(self, include_hidden: bool = False, hidden_only: bool = False, include_debug: bool = False,
                     flatten: bool = False) -> List[str]:
        """
        :param include_hidden: Whether to include commands with the `hidden` flag set.
        :param hidden_only: Whether to only return commands with the `hidden` flag set. Requires `include_hidden`.
        :param include_debug: Whether to include commands in the debug plugin.
        :param flatten: If set to True, recursively includes subcommands
        :return: A list of all commands.
        """
        plugins = [self.cog]
        for plugin in self.bot.plugin_objects(plugins_only=True):
            if include_debug or "debug" not in plugin.get_name():
                plugins.append(plugin)
        cmds = []
        for plugin in plugins:
            cmditer = plugin.walk_commands if flatten else plugin.get_commands
            for cmd in cmditer():
                if hidden_only and not cmd.hidden:
                    continue
                if cmd.hidden and not include_hidden:
                    continue
                cmds.append(self.format_command_help_line(plugin, cmd))

        return sorted(cmds)

    #####
    # Evaluation methods
    #####
    @staticmethod
    def get_command_help(plugin: BasePlugin, cmd: commands.Command) -> str:
        """
        :param plugin: Plugin that `cmd` is in
        :param cmd: Command to get help string for
        :return: Help string for `cmd`
        """
        r = None
        try:
            r = plugin.command_help_string(cmd)
        except NotFound:
            if cmd.help is not None and cmd.help.strip():
                r = cmd.help
        return r

    def get_command_description(self, plugin: BasePlugin, cmd: commands.Command) -> str:
        """
        :param plugin: Plugin that `cmd` is in
        :param cmd: Command to get description string for
        :return: Description string for `cmd`
        """
        try:
            desc = plugin.command_description(cmd)
        except NotFound:
            if cmd.description is not None and cmd.description.strip():
                desc = cmd.description
            else:
                desc = self.get_command_help(plugin, cmd)

        if desc is None:
            desc = Lang.lang(self, "help_no_desc")

        return desc + "\n"

    #####
    # Format methods
    #####
    def _append_command_leaves(self, cmds: List[commands.Command], cmd: commands.Command):
        """
        Recursive helper function for `flattened_plugin_help()`.

        :param cmds: list to append the leaves to
        :param cmd: Command or Group
        """
        if not isinstance(cmd, commands.Group):
            cmds.append(cmd)
            return

        # we are in a group
        for command in cmd.commands:
            self._append_command_leaves(cmds, command)

    def flattened_plugin_help(self, plugin: BasePlugin) -> List[str]:
        """
        In the tree structure of existing commands and groups in a plugin, returns a list of all
        formatted leaf command help lines.

        :param plugin: Plugin to create a flattened command help for
        :return: Msg list to be consumed by utils.paginate()
        """
        cmds = []
        for cmd in plugin.get_commands():
            self._append_command_leaves(cmds, cmd)

        msg = []
        for cmd in cmds:
            msg.append(self.format_command_help_line(plugin, cmd))
        return msg

    def format_command_help_line(self, plugin: BasePlugin, command: commands.Command) -> str:
        """
        :param plugin: BasePlugin object that this command belongs to
        :param command: Command that the help line concerns
        :return: One-line string that represents a help list entry for `command`
        """
        try:
            helpstr = plugin.command_help_string(command)
        except (NotFound, AttributeError):
            helpstr = command.help
        if helpstr is not None and helpstr.strip():
            return "{}{} - {}".format(self.bot.command_prefix, command.qualified_name, helpstr)
        return "{}{}".format(self.bot.command_prefix, command.qualified_name)

    def format_subcmds(self, ctx: commands.Context, plugin: BasePlugin, command: commands.Command) -> List[str]:
        """
        Brings the subcommands of a command in format to be used in a help message.

        :param ctx: Context
        :param plugin: Plugin that cmd is in
        :param command: Command whose subcommands are to be listed
        :return: Formatted list of subcommands
        """
        r = []
        if isinstance(command, commands.Group):
            for cmd in plugin.sort_commands(ctx, command, command.commands):
                if cmd.hidden:
                    continue
                r.append("  {}".format(self.format_command_help_line(plugin, cmd)))
            if r:
                r = [Lang.lang(self, "help_subcommands_prefix")] + r
        return r

    def format_aliases(self, command: commands.Command) -> str:
        """
        Brings the aliases of a command in format to be used in a help message.

        :param command: Command whose aliases are to be listed
        :return: Formatted list of aliases
        """
        aliases = ", ".join(command.aliases)
        return Lang.lang(self, "help_aliases", aliases) + "\n"

    def format_usage(self, cmd: commands.Command, plugin: BasePlugin = None) -> str:
        """
        Brings the usage of a command in format to be used in a help message.

        :param cmd: Command whose usage is to be listed
        :param plugin: Plugin that `cmd` is in; can be omitted to ignore plugin-specific usage msg
        :return: Formatted command usage string
        """
        if plugin is None:
            plugin = get_plugin_by_cmd(cmd)

        parent = self.bot.command_prefix + cmd.qualified_name
        try:
            usage = plugin.command_usage(cmd)
        except NotFound:
            if cmd.usage is None or not cmd.usage.strip():
                usage = cmd.signature
            else:
                usage = cmd.usage
        return "{} {}".format(parent, usage)

    ######
    # Output methods
    ######
    async def error(self, ctx, error):
        await ctx.send(Lang.lang(self, error))

    async def cmd_help(self, ctx, plugin, cmd):
        """
        Sends a help message for a command.

        :param ctx: Context to send the help message to
        :param plugin: Plugin that contains the command
        :param cmd: Command the help message concerns
        """
        try:
            await plugin.command_help(ctx, cmd)
            return
        except NotFound:
            pass

        # Usage
        msg = [self.format_usage(cmd, plugin=plugin) + "\n"]

        # Aliases
        if len(cmd.aliases) > 0:
            msg.append(self.format_aliases(cmd))

        # Help / Description
        msg.append(self.get_command_description(plugin, cmd))

        msg += self.format_subcmds(ctx, plugin, cmd)

        # Subcommands
        for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

    ######
    # Commands
    ######
    async def helpcmd(self, ctx, *args):
        """
        Handles any help command.

        :param ctx: Context
        :param args: Arguments that the help command was called with
        """
        # !help
        if len(args) == 0:
            # build ordering lists
            first = []
            middle = []
            last = []
            for cat in self._categories:
                if cat.is_empty():
                    self.logger.debug("Ignoring category %s as it is empty", cat.name)
                    continue

                line = "  {}".format(cat.single_line())
                if cat.order == CategoryOrder.FIRST:
                    first.append(line)
                elif cat.order == CategoryOrder.LAST:
                    last.append(line)
                else:
                    middle.append(line)

            for msg in paginate(first + middle + last,
                                prefix=Lang.lang(self, "help_categories_prefix") + "\n",
                                msg_prefix="```",
                                msg_suffix="```"):
                await ctx.send(msg)
            return

        # !help args
        # find command
        plugin, cmd = self.find_command(args)
        if cmd is not None:
            await self.cmd_help(ctx, plugin, cmd)
            return

        # find category
        if len(args) != 1:
            # no category
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.error(ctx, "cmd_not_found")
            return
        cat = None
        for el in self._categories:
            if el.match_name(args[0]):
                cat = el
                break
        if cat is not None and not cat.is_empty():
            await cat.send_category_help(ctx)
            return

        await add_reaction(ctx.message, Lang.CMDERROR)
        await self.error(ctx, "cmd_cat_not_found")

    async def usagecmd(self, ctx, *args):
        """
        Handles any usage command.

        :param ctx: Context
        :param args: Arguments that the usage command was called with
        """
        if not args:
            await self.bot.helpsys.cmd_help(ctx, self.cog, ctx.command)
            return

        plugin, cmd = self.find_command(args)
        if cmd is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.error(ctx, "cmd_not_found")
            return

        await ctx.send("```{}```".format(self.format_usage(cmd, plugin=plugin)))

    async def listcmd(self, ctx, *args):
        """
        Handles any helpall command.

        :param ctx: Context
        """
        debug = "debug" in args
        hidden = "hidden" in args
        recursive = "recursive" in args
        cmds = self.all_commands(include_hidden=hidden, include_debug=debug, flatten=recursive)
        prefix = Lang.lang(self, "help_all_length", len(cmds)) + "\n"
        for msg in paginate(cmds, prefix=prefix, msg_prefix="```", msg_suffix="```", prefix_within_msg_prefix=False):
            await ctx.send(msg)

    async def hiddencmd(self, ctx: Context, *args):
        """
        Handles and help hidden command.

        :param ctx: Context
        :param args: Arguments of the "hidden" cmd; currently supported: debug
        """
        debug = "debug" in args
        msgs = self.all_commands(hidden_only=True, include_hidden=True, include_debug=debug, flatten=True)
        for msg in paginate(msgs, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

    async def locatecmd(self, ctx, *args):
        """
        Shows the plugin name that a given cmd belongs to.

        :param ctx: Context
        :param args: Arguments that the locate command was called with
        """
        if not args:
            await self.bot.helpsys.cmd_help(ctx, self.cog, ctx.command)
            return

        plugin, cmd = self.find_command(args)
        if cmd is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.error(ctx, "cmd_not_found")
            return

        await ctx.send(Lang.lang(self.cog, "locate", plugin.get_name()))
