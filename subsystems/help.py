from enum import Enum

from discord.ext import commands

from base import BaseSubsystem, NotFound
from conf import Lang
from botutils.stringutils import paginate


class CategoryNotFound(Exception):
    pass


class CategoryExists(Exception):
    pass


class DefaultCategories(Enum):
    MISC = 0
    ADMIN = 1
    MOD = 2
    GAMES = 3


class CategoryOrder(Enum):
    FIRST = 0
    MIDDLE = 1
    LAST = 2


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.command(name="help")
    async def helpcmd(self, ctx, *args):
        await self.bot.helpsys.helpcmd(ctx, *args)


class HelpCategory:
    def __init__(self, name, description="", order=CategoryOrder.MIDDLE, bot=None):
        self._name = name[0].upper() + name[1:]
        self.description = description
        self.plugins = []
        self.order = order
        self.bot = bot

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
        return len(self.plugins) == 0

    def add_plugin(self, plugin):
        """
        Adds a plugin to this HelpCategory.
        :param plugin: BasePlugin instance to be added to the category
        """
        self.plugins.append(plugin)

    def single_line(self):
        """
        :return: One-line string that represents this HelpCategory.
        """
        if self.description:
            return "{} - {}".format(self.name, self.description)
        else:
            return self.name

    def format_commands(self):
        """
        :return: Message list with all commands that this category contains to be consumed by paginate().
        """
        r = []
        for plugin in self.plugins:
            for command in plugin.get_commands():
                r.append("  {}".format(self.bot.helpsys.format_command_help_line(command)))
        return r

    async def send_category_help(self, ctx):
        """
        Sends a help message for this category.
        :param ctx: Context that the help message is to be sent to.
        """
        msg = self.format_commands()
        for msg in paginate(msg,
                            prefix=Lang.lang(self.bot.helpsys, "help_category_prefix", self.name) + "\n",
                            msg_prefix="```",
                            msg_suffix="```"):
            await ctx.send(msg)


class GeckiHelp(BaseSubsystem):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(self.bot)

        self._categories = [
            HelpCategory(Lang.lang(self, "default_category_misc"), order=CategoryOrder.LAST, bot=bot),
            HelpCategory(Lang.lang(self, "default_category_admin"), bot=bot),
            HelpCategory(Lang.lang(self, "default_category_mod"), bot=bot),
            HelpCategory(Lang.lang(self, "default_category_games"), bot=bot),
        ]

        # Setup help cmd
        self.bot.remove_command("help")
        self.cog = HelpCog(self.bot)
        self.bot.add_cog(self.cog)

    """
    Housekeeping methods
    """
    def default_category(self, const):
        """
        :param const: One out of DefaultCategories
        :return: Corresponding registered category
        """
        langstr = None
        if const == DefaultCategories.MISC:
            langstr = "default_category_misc"
        elif const == DefaultCategories.ADMIN:
            langstr = "default_category_admin"
        elif const == DefaultCategories.MOD:
            langstr = "default_category_mod"
        elif const == DefaultCategories.GAMES:
            langstr = "default_category_games"

        r = self.category(Lang.lang(self, langstr))
        assert r is not None
        return r

    def category(self, name):
        """
        :param name: Category name
        :return: Returns the HelpCategory with name `name`. None if no such HelpCategory is found.
        """
        for cat in self._categories:
            if cat.match_name(name):
                return cat
        return None

    def register_category_by_name(self, name, description=""):
        cat = self.category(name)
        if cat is None:
            cat = HelpCategory(name, description=description)
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

    """
    Parsing methods
    """
    def find_command(self, cmdname, context):
        """
        :return: (plugin, command).
        `plugin` is the plugin that registered this command.
        `command` is a Command with the name `cmdname` in the group `context`.
        If `context` is None, finds the top-level command with name `cmdname` and sets plugin to the
        containing plugin. Otherwise, `plugin` is None.
        If nothing is found, returns None, None.
        """
        # Find top-level command
        if context is None:
            for plugin in self.bot.plugin_objects(plugins_only=True):
                for cmd in plugin.get_commands():
                    if cmd.name == cmdname:  # TODO aliases
                        return plugin, cmd
            return None, None

        # Find command in group
        if isinstance(context, commands.Group):
            return None, context.get_command(cmdname)
        else:
            return None, None

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
        except NotFound:
            helpstr = command.help
        if helpstr is not None and helpstr.strip():
            return "{}{} - {}".format(self.bot.command_prefix, command.qualified_name, helpstr)
        else:
            return "{}{}".format(self.bot.command_prefix, command.qualified_name)

    def format_subcmds(self, plugin, command):
        r = []
        if isinstance(command, commands.Group):
            for cmd in command.commands:
                r.append("  {}".format(self.format_command_help_line(plugin, cmd)))
            if r:
                r = [Lang.lang(self, "help_subcommands_prefix")] + r
        return r

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
        msg = []

        # Usage
        parent = self.bot.command_prefix + cmd.qualified_name
        usage = cmd.usage
        if usage is None or not usage.strip():
            usage = cmd.signature
        usage = "{} {}".format(parent, usage)
        msg.append(usage + "\n")

        # Help / Description
        try:
            desc = plugin.command_description(cmd) + "\n"
        except NotFound:
            desc = cmd.qualified_name + "\n"
            if cmd.help is not None and cmd.help.strip():
                desc = cmd.help + "\n"
            if cmd.description is not None and cmd.description.strip():
                desc = cmd.description + "\n"
        msg.append(desc)
        msg += self.format_subcmds(plugin, cmd)

        # Subcommands
        for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

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
                    continue

                line = "  {}".format(cat.single_line())
                if cat.order == CategoryOrder.FIRST:
                    first.append(line)
                elif cat.order == CategoryOrder.LAST:
                    last.append(line)
                else:
                    middle.append(line)

            lines = first + middle + last
            for msg in paginate(lines,
                                prefix=Lang.lang(self, "help_categories_prefix") + "\n",
                                msg_prefix="```",
                                msg_suffix="```"):
                await ctx.send(msg)
            return

        # !help args
        else:
            # find command
            cmd = None
            plugin = None
            for arg in args:
                p, cmd = self.find_command(arg, cmd)
                if p is not None:
                    plugin = p
            if cmd is not None:
                await self.cmd_help(ctx, plugin, cmd)
                return

            # find category
            if len(args) != 1:
                # no category
                await ctx.message.add_reaction(Lang.CMDERROR)
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

            await ctx.message.add_reaction(Lang.CMDERROR)
            await self.error(ctx, "cmd_cat_not_found")
