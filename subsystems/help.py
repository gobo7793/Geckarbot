from enum import Enum

from discord.ext import commands

from base import BaseSubsystem, BasePlugin
from conf import Lang
from botutils.utils import paginate


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


def command_help_line(command):
    return command.name


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.command(name="help")
    async def helpcmd(self, ctx, *args):
        await self.bot.helpsys.helpcmd(ctx, *args)


class HelpCategory:
    def __init__(self, name, description="", order=CategoryOrder.MIDDLE):
        self._name = name[0].upper() + name[1:]
        self.description = description
        self.plugins = []
        self.order = order

    @property
    def name(self):
        return self._name

    def has_plugins(self):
        return len(self.plugins) > 0

    def add_plugin(self, plugin):
        self.plugins.append(plugin)

    def single_line(self):
        if self.description:
            return "{} - {}".format(self.name, self.description)
        else:
            return self.name

    def to_help(self):
        msg = [self.single_line()]
        for plugin in self.plugins:
            for command in plugin.get_commands():
                msg.append("  {}".format(command_help_line(command)))
        return msg


class GeckiHelp(BaseSubsystem):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(self.bot)

        self._categories = [
            HelpCategory(Lang.lang(self, "default_category_misc"), order=CategoryOrder.LAST),
            HelpCategory(Lang.lang(self, "default_category_admin")),
            HelpCategory(Lang.lang(self, "default_category_mod")),
            HelpCategory(Lang.lang(self, "default_category_games")),
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
            langstr = "default_category_misc"

        r = self.category(Lang.lang(self, langstr))
        assert r is not None
        return r

    def category(self, name):
        for cat in self._categories:
            if cat.name.lower() == name.lower():
                return cat
        return None

    def register_category_by_name(self, name, description=""):
        cat = self.category(name)
        if cat is None:
            cat = HelpCategory(name, description=description)
            self.register_category(cat)
        return cat

    def register_category(self, category):
        # Catch default category
        if isinstance(category, DefaultCategories):
            return self.default_category(category)

        exists = self.category(category.name)
        if exists:
            raise CategoryExists(category.name)

        self._categories.append(category)
        return category

    """
    Parsing methods
    """
    def find_command(self, cmdname, context):
        """
        :return: command with the name `cmdname` in the group `context`. If `context` is None,
        finds the top-level command with name `cmdname`. If nothing is found, returns None.
        """
        # Find top-level command
        if context is None:
            for plugin in self.bot.plugin_objects(plugins_only=True):
                for cmd in plugin.get_commands():
                    if cmd.name == cmdname:  # TODO aliases
                        return cmd
            return None

        # Find command in group
        if isinstance(context, commands.Group):
            return context.get_command(cmdname)
        else:
            return None

    """
    Output methods
    """
    async def cmd_not_found(self, ctx):
        await ctx.send(Lang.lang(self, "cmd_not_found"))

    async def full_cmd_help(self, ctx, cmd):
        await ctx.send("Dies ist die vollständige Hilfe für {}".format(cmd.name))

    async def helpcmd(self, ctx, *args):
        # !help
        if len(args) == 0:
            # build ordering lists
            first = []
            middle = []
            last = []
            for cat in self._categories:
                line = cat.single_line()
                if cat.order == CategoryOrder.FIRST:
                    first.append(line)
                elif cat.order == CategoryOrder.LAST:
                    last.append(line)
                else:
                    middle.append(line)

            lines = first + middle + last
            for msg in paginate(lines, prefix=Lang.lang(self, "help_pre_text") + "\n\n", msg_prefix="```",
                                msg_suffix="```"):
                await ctx.send(msg)
            return

        # !help args
        else:
            # find command that was specified
            cmd = None
            for arg in args:
                cmd = self.find_command(arg, cmd)
            if cmd is not None:
                await self.full_cmd_help(ctx, cmd)
