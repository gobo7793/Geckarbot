from enum import Enum
import logging

from discord.ext import commands

from base import BaseSubsystem, NotFound, BasePlugin, ConfigurableType
from botutils.utils import add_reaction, get_plugin_by_cmd
from data import Lang
from botutils.stringutils import paginate


class CategoryNotFound(Exception):
    pass


class CategoryExists(Exception):
    pass


class DefaultCategories(Enum):
    UTILS = 0
    GAMES = 1
    SPORT = 2
    MISC = 3
    USER = 4
    MOD = 5
    ADMIN = 6


class CategoryOrder(Enum):
    FIRST = 0
    MIDDLE = 1
    LAST = 2


class HelpCog(BasePlugin):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        self.category = HelpCategory(bot, Lang.lang(self, "self_category_name"))
        self.category.add_plugin(self)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    @commands.command(name="help")
    async def helpcmd(self, ctx, *args):
        await self.bot.helpsys.helpcmd(ctx, *args)

    @commands.command(name="usage")
    async def usagecmd(self, ctx, *args):
        await self.bot.helpsys.usagecmd(ctx, *args)

    @commands.command(name="helpall")
    async def listcmd(self, ctx, *args):
        await self.bot.helpsys.listcmd(ctx, *args)

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.name))

    def command_description(self, command):
        return Lang.lang(self, "description_{}".format(command.name))

    def command_usage(self, command):
        return Lang.lang(self, "usage_{}".format(command.name))


class HelpCategory:
    def __init__(self, bot, name, description="", order=CategoryOrder.MIDDLE, defaultcat=False):
        self._name = name[0].upper() + name[1:]
        self.description = description
        self.plugins = []
        self.standalone_commands = []
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

    def match_name(self, name):
        """
        :return: `True` if `name` is a valid name for this category, `False` otherwise.
        """
        if name.lower() == self.name.lower():
            return True
        return False

    def is_empty(self):
        """
        :return: True if this HelpCategory does not contain any plugins, False otherwise.
        """
        return len(self.plugins) == 0 and len(self.standalone_commands) == 0

    def add_plugin(self, plugin):
        """
        Adds a plugin to this HelpCategory.
        
        :param plugin: BasePlugin instance to be added to the category
        """
        self.plugins.append(plugin)

    def remove_plugin(self, plugin):
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

    def add_command(self, command):
        """
        Adds a standalone command to this HelpCategory.

        :param command: Command that is to be added to the category
        """
        self.standalone_commands.append(command)

    def remove_command(self, command):
        """
        Removes a standalone command from this HelpCategory.

        :param command: Command that is to be removed from the category
        """
        while command in self.standalone_commands:
            self.standalone_commands.remove(command)

    def single_line(self):
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
                r.append(cmd)
        return r + self.standalone_commands

    def sort_commands(self, ctx, cmds):
        return sorted(cmds, key=lambda x: x.name)

    def format_commands(self, ctx):
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


class GeckiHelp(BaseSubsystem):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(self.bot)
        self.logger = logging.getLogger(__name__)

        self.default_categories = {
            DefaultCategories.UTILS: HelpCategory(bot, Lang.lang(self, "default_category_utils"),
                                                  order=CategoryOrder.FIRST, defaultcat=True),
            DefaultCategories.GAMES: HelpCategory(bot, Lang.lang(self, "default_category_games"),
                                                  defaultcat=True),
            DefaultCategories.SPORT: HelpCategory(bot, Lang.lang(self, "default_category_sport"),
                                                  defaultcat=True),
            DefaultCategories.MISC: HelpCategory(bot, Lang.lang(self, "default_category_misc"),
                                                 order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.USER: HelpCategory(bot, Lang.lang(self, "default_category_user"),
                                                 order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.MOD: HelpCategory(bot, Lang.lang(self, "default_category_mod"),
                                                order=CategoryOrder.LAST, defaultcat=True),
            DefaultCategories.ADMIN: HelpCategory(bot, Lang.lang(self, "default_category_admin"),
                                                  order=CategoryOrder.LAST, defaultcat=True),
        }

        self._categories = [self.default_categories[x] for x in self.default_categories]

        # Setup help cmd
        self.bot.remove_command("help")
        self.cog = HelpCog(self.bot)
        self.bot.add_cog(self.cog)
        self.register_category(self.cog.category)

    """
    Housekeeping methods
    """
    def default_category(self, const):
        """
        :param const: One out of DefaultCategories
        :return: Corresponding registered category
        """
        return self.default_categories[const]

    def category(self, name):
        """
        :param name: Category name
        :return: Returns the HelpCategory with name `name`. None if no such HelpCategory is found.
        """
        for cat in self._categories:
            if cat.match_name(name):
                return cat
        return None

    def categories_by_plugin(self, plugin):
        """
        :param plugin: Plugin
        :return: List of HelpCategory objects that contain `plugin`
        """
        r = []
        for cat in self._categories:
            if plugin in cat.plugins:
                r.append(cat)
        return r

    def register_category_by_name(self, name, description=""):
        cat = self.category(name)
        if cat is None:
            cat = HelpCategory(self.bot, name, description=description)
            self.register_category(cat)
        return cat

    def register_category(self, category):
        """
        Registers a category with Help. If a DefaultCategory is parsed, nothing is registered,
        but the corresponding registered HelpCategory is returned.

        :param category: HelpCategory instance or DefaultCategory instance
        :return: The registered HelpCategory
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

    def deregister_category(self, category):
        """
        Deregisters a help category. If a DefaultCategory is parsed, nothing is deregistered.

        :param category: HelpCategory instance or DefaultCategory instance
        """
        if isinstance(category, DefaultCategories):
            return

        exists = self.category(category.name)
        if not exists:
            raise CategoryNotFound(category.name)

        self._categories.remove(category)

    def purge_plugin(self, plugin):
        cats = self.categories_by_plugin(plugin)
        for cat in cats:
            cat.remove_plugin(plugin)
        for cmd in plugin.get_commands():
            for cat in self._categories:
                cat.remove_command(cmd)

    """
    Parsing methods
    """
    def find_command(self, args):
        """
        Finds the command that is resembled by `args`.

        :return: `(plugin, command)`.
            `plugin` is the plugin where the found command `command` is registered in.
            If nothing is found, returns `(None, None)`.
        """
        plugins = [self.cog] + [el for el in self.bot.plugin_objects(plugins_only=True)]

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
        else:
            return None, None

    """
    Evaluation methods
    """
    @staticmethod
    def get_command_help(plugin, cmd):
        r = None
        try:
            r = plugin.command_help_string(cmd)
        except NotFound:
            if cmd.help is not None and cmd.help.strip():
                r = cmd.help
        return r

    def get_command_description(self, plugin, cmd):
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

    """
    Format methods
    """
    def append_command_leaves(self, cmds, cmd):
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
            self.append_command_leaves(cmds, command)

    def flattened_plugin_help(self, plugin):
        """
        In the tree structure of existing commands and groups in a plugin, returns a list of all
        formatted leaf command help lines.

        :param plugin: Plugin to create a flattened command help for
        :return: Msg list to be consumed by utils.paginate()
        """
        cmds = []
        for cmd in plugin.get_commands():
            self.append_command_leaves(cmds, cmd)

        msg = []
        for cmd in cmds:
            msg.append(self.format_command_help_line(plugin, cmd))
        return msg

    def format_command_help_line(self, plugin, command):
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
        else:
            return "{}{}".format(self.bot.command_prefix, command.qualified_name)

    def format_subcmds(self, ctx, plugin, command):
        r = []
        if isinstance(command, commands.Group):
            for cmd in plugin.sort_commands(ctx, command, command.commands):
                if cmd.hidden:
                    continue
                r.append("  {}".format(self.format_command_help_line(plugin, cmd)))
            if r:
                r = [Lang.lang(self, "help_subcommands_prefix")] + r
        return r

    def format_aliases(self, command):
        aliases = ", ".join(command.aliases)
        r = Lang.lang(self, "help_aliases", aliases) + "\n"
        return r

    def format_usage(self, cmd, plugin=None):
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

    """
    Output methods
    """
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

    """
    Commands
    """
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
                    self.logger.debug("Ignoring category {} as it is empty".format(cat.name))
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
        else:
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
        debug = False
        if "debug" in args:
            debug = True
        plugins = [self.cog]
        for plugin in self.bot.plugin_objects(plugins_only=True):
            if debug or "debug" not in plugin.get_name():
                plugins.append(plugin)
        cmds = []
        for plugin in plugins:
            for cmd in plugin.get_commands():
                cmds.append(self.format_command_help_line(plugin, cmd))

        cmds = sorted(cmds)
        for msg in paginate(cmds, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)
