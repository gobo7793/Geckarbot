from discord.ext import commands

from base import BaseSubsystem, BasePlugin
from conf import Lang
from botutils.utils import paginate


class CategoryNotFound(Exception):
    pass


class CategoryExists(Exception):
    pass


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
    def __init__(self, name, description=""):
        self._name = name[0].upper() + name[1:]
        self.description = description
        self.plugins = []

    @property
    def name(self):
        return self._name

    def has_plugins(self):
        return len(self.plugins) > 0

    def add_plugin(self, plugin):
        self.plugins.append(plugin)

    def to_string(self):
        if self.description:
            return "{} - {}".format(self.name, self.description)
        else:
            return self.name

    def to_help(self):
        msg = [self.to_string()]
        for plugin in self.plugins:
            for command in plugin.get_commands():
                msg.append("  {}".format(command_help_line(command)))
        return msg


class GeckiHelp(BaseSubsystem):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(self.bot)

        self._categories = [
            HelpCategory(Lang.lang(self, "default_category_misc")),
            HelpCategory(Lang.lang(self, "default_category_games")),
        ]

        # Setup help cmd
        self.bot.remove_command("help")
        self.cog = HelpCog(self.bot)
        self.bot.add_cog(self.cog)

    """
    Housekeeping methods
    """
    def category(self, name):
        for cat in self._categories:
            if cat.name.lower() == name.lower():
                return cat
        return None

    def create_or_get_category(self, name, description=""):
        cat = self.category(name)
        if cat is None:
            cat = HelpCategory(name, description=description)
        return cat

    def register_category(self, category):
        exists = self.category(category.name)
        if exists:
            raise CategoryExists(category.name)

        self._categories.append(category)

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
            lines = []
            for cat in self._categories:
                lines = lines + cat.to_help()

            for msg in paginate(lines, prefix=Lang.lang(self, "help_pre_text"), msg_prefix="```",
                                msg_suffix="```"):
                await ctx.send(msg)
            return

        # !help args
        else:
            # find command that was specified
            cmd = None
            for arg in args:
                cmd = self.find_command(arg, cmd)
                if cmd is None:
                    await self.cmd_not_found(ctx)
                    return
            await self.full_cmd_help(ctx, cmd)
