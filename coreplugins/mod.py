import platform
import discord
import pkgutil
from discord.ext import commands

from conf import Storage, Config, Lang, reconfigure
from botutils import utils, permChecks
from base import BasePlugin, ConfigurableType
import subsystems
from subsystems.ignoring import IgnoreEditResult, IgnoreType


class Plugin(BasePlugin, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

    def default_config(self):
        return {
            'repo_link': "https://github.com/gobo7793/Geckarbot/",
            'bot_info_link': "",
            'privacy_notes_link': "",
            'privacy_notes_lang': "",
            'profile_pic_creator': ""
        }

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    ######
    # Misc commands
    ######

    # @commands.command(name="reload", help="Reloads the configuration.", usage="[plugin_name]",
    #                   description="Reloads the configuration from the given plugin."
    #                               "If no plugin given, all plugin configs will be reloaded.")
    # @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID)
    # async def reload(self, ctx, plugin_name=None):
    #     """Reloads the config of the given plugin or all if none is given"""
    #     await utils.log_to_admin_channel(ctx)
    #     if plugin_name is None:
    #         reconfigure(self.bot)
    #         send_msg = "Configuration of all plugins reloaded."
    #     else:
    #         send_msg = f"No plugin {plugin_name} found."
    #         for plugin in self.bot.plugins:
    #             if plugin.name == plugin_name:
    #                 if plugin.instance.can_reload:
    #                     self.bot.configure(plugin.instance)
    #                     send_msg = f"Configuration of plugin {plugin_name} reloaded."
    #                 else:
    #                     send_msg = f"Plugin {plugin_name} can't reloaded."
    #
    #     if ctx.channel.id != Config().DEBUG_CHAN_ID:
    #         await ctx.send(send_msg)
    #     await utils.write_debug_channel(self.bot, send_msg)

    @commands.command(name="plugins", help="List all plugins.")
    async def plugins(self, ctx):
        """Returns registered plugins"""
        coreplugins = [c.name for c in self.bot.plugins if c.type == ConfigurableType.COREPLUGIN]
        plugins = [c.name for c in self.bot.plugins if c.type == ConfigurableType.PLUGIN]
        subsys = []
        for modname in pkgutil.iter_modules(subsystems.__path__):
            subsys.append(modname.name)

        for msg in utils.paginate(coreplugins, prefix=f"Loaded {len(coreplugins)} coreplugins:\n", delimiter=", "):
            await ctx.send(msg)
        for msg in utils.paginate(plugins, prefix=f"Loaded {len(plugins)} plugins:\n", delimiter=", "):
            await ctx.send(msg)
        for msg in utils.paginate(subsys, prefix=f"Installed {len(subsys)} subsystems:\n", delimiter=", "):
            await ctx.send(msg)

    @commands.command(name="about", aliases=["git", "github"], help="Prints the credits")
    async def about(self, ctx):
        about_msg = "Geckarbot {} on {}, licensed under GNU GPL v3.0. Hosted with ❤ on {} {} {}.\n".format(
            Config().VERSION, self.bot.guild.name, platform.system(), platform.release(), platform.version())

        if Storage().get(self)['bot_info_link']:
            about_msg += "For general bot information on this server see <{}>.\n".format(
                Storage().get(self)['bot_info_link'])
        about_msg += "Github Repository for additional information and participation: <{}>.\n".format(
            Storage().get(self).get('repo_link', "Please ask your local bot manager."))
        if Storage().get(self)['privacy_notes_link']:
            lang = ""
            if Storage().get(self)['privacy_notes_lang']:
                lang = " ({})".format(Storage().get(self)['privacy_notes_lang'])
            about_msg += "Privacy notes: <{}>{}.\n".format(Storage().get(self)['privacy_notes_link'], lang)

        about_msg += "Main developers: Costamiri, Fluggs, Gobo77."
        if Storage().get(self)['profile_pic_creator']:
            about_msg += " Profile picture by {}.".format(Storage().get(self)['profile_pic_creator'])

        about_msg += "\nSpecial thanks to all contributors!"

        await ctx.send(about_msg)

    ######
    # Ignoring subsystem
    ######

    @commands.group(name="disable", invoke_without_command=True, help="Blocks user or command usage.",
                    brief="Blocks user or command usage", aliases=["ignore", "block"],
                    usage="<command> [user] [#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]",
                    description="Adds a command to users ignore list to disable any interactions between the user and "
                                "the command.\n"
                                "To block command usage for the user, the command name must be the full qualified "
                                "name of the command without command prefix. If a subcommand should be blocked, "
                                "the command name must be inside quotation marks like \"disable cmd\".\n "
                                "To block other interactions than command usage itself, the command must support "
                                "blocking usage for specific users.\n"
                                "The time can be a fixed date and/or time or a duration after that the "
                                "command will be auto-removed from the ignore list. The duration unit must be set "
                                "with trailing m for minutes, h for hours or d for days. If no date/duration is "
                                "given, the user can't interact with that command forever.\n"
                                "Users can disable command interactions for themselves only, but Admins also for "
                                "other users.\n"
                                "If a user uses a command which is blocked for the user, "
                                "the bot doesn't response anything, like the command wouldn't exists.")
    async def disable(self, ctx, command, *args):
        user = ctx.author
        date_args_start_index = 0
        if len(args) > 0:
            try:
                user = await commands.MemberConverter().convert(ctx, args[0])
                date_args_start_index = 1
            except (commands.CommandError, IndexError):
                date_args_start_index = 0

        if user != ctx.author and not permChecks.check_full_access(ctx.author):
            raise commands.MissingAnyRole(Config().FULL_ACCESS_ROLES)

        until = utils.analyze_time_input(*args[date_args_start_index:])

        result = self.bot.ignoring.add_user_command(user, command, until)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Already_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Interactions with command {} are already blocked for {}."
                           .format(command, utils.get_best_username(user)))
        elif result == IgnoreEditResult.Until_in_past:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Sorry, I don't have a time machine.")
        await utils.log_to_admin_channel(ctx)

    @disable.command(name="user", help="Block any interaction between user and bot.",
                     usage="<user> [#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]",
                     description="Adds a user to bot's ignore list to block any interaction between the user and the "
                                 "bot.\n "
                                 "The time can be a fixed date and/or time or a duration after that the user will be "
                                 "auto-removed from the ignore list. The duration unit must be set with trailing m "
                                 "for minutes, h for hours or d for days. If no date/duration is given, the user will "
                                 "be blocked forever.\n"
                                 "If a blocked user uses a command, "
                                 "the bot doesn't response anything, like the command wouldn't exists.")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def disable_user(self, ctx, user: discord.Member, *args):
        until = utils.analyze_time_input(*args)

        result = self.bot.ignoring.add_user(user, until)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Already_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("{} already blocked.".format(utils.get_best_username(user)))
        elif result == IgnoreEditResult.Until_in_past:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Sorry, I don't have a time machine.")
        await utils.log_to_admin_channel(ctx)

    @disable.command(name="cmd", help="Disables a command in current channel.",
                     usage="<command> [#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]",
                     description="Adds a command to bot's ignore list to disable it in current channel. The command "
                                 "name must be the full qualified name of the command without command prefix. If a "
                                 "subcommand should be blocked, the command name must be inside quotation marks like "
                                 "\"disable cmd\".\n"
                                 "The time can be a fixed date and/or time or a duration after that the command will "
                                 "be auto-removed from the ignore list. The duration unit must be set with trailing m "
                                 "for minutes, h for hours or d for days. If no date/duration is given, the command "
                                 "will be disabled forever.\n"
                                 "If a user uses a command which is blocked in the channel, "
                                 "the bot doesn't response anything, like the command wouldn't exists.\n"
                                 "Note: The command !enable can't be blocked to avoid deadlocks.")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def disable_cmd(self, ctx, command, *args):
        if command == "enable":
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Command `!enable` can't be blocked to avoid blocking deadlocks.")
            return

        until = utils.analyze_time_input(*args)

        result = self.bot.ignoring.add_command(command, ctx.channel, until)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Already_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Command {} already blocked in this channel".format(command))
        elif result == IgnoreEditResult.Until_in_past:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Sorry, I don't have a time machine.")
        await utils.log_to_admin_channel(ctx)

    @disable.command(name="list", help="Lists all blocked users and commands")
    # NOTE: Will be invoked via "!subsys"
    async def disable_list(self, ctx):
        def get_item_msg(item):
            return item.to_message()

        async def write_list(itype: IgnoreType, prefix):
            ilist = self.bot.ignoring.get_ignore_list(itype)
            if len(ilist) > 0:
                for msg in utils.paginate(ilist, prefix=prefix, f=get_item_msg):
                    await ctx.send(msg)

        if self.bot.ignoring.get_full_ignore_len() < 1:
            await ctx.send("No users or commands blocked.")
            return

        await write_list(IgnoreType.User, "**Blocked Users:**\n")
        await write_list(IgnoreType.Command, "**Disabled Commands:**\n")
        await write_list(IgnoreType.User_Command, "**Blocked Commands for Users:**\n")

    @commands.group(name="enable", invoke_without_command=True, help="Unblocks user or command usage.",
                    aliases=["unignore", "unblock"],
                    description="Removes a command from users ignore list to enable any interactions between the user "
                                "and the command.\n"
                                "Users can enable command interactions for themselves only, but Admins also for "
                                "other users.")
    async def enable(self, ctx, command, user: discord.Member = None):
        if user is None:
            user = ctx.author

        if user != ctx.author and not permChecks.check_full_access(ctx.author):
            raise commands.MissingAnyRole(*Config().FULL_ACCESS_ROLES)

        result = self.bot.ignoring.remove_user_command(user, command)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Not_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Interactions with command {} are not blocked for {}."
                           .format(command, utils.get_best_username(user)))
        await utils.log_to_admin_channel(ctx)

    @enable.command(name="user", help="Unblock user to enable interactions between user and bot.",
                    description="Removes a user from bot's ignore list to enable any interaction between the user and "
                                "the bot.")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def enable_user(self, ctx, user: discord.Member):
        result = self.bot.ignoring.remove_user(user)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Not_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("{} is not blocked.".format(utils.get_best_username(user)))
        await utils.log_to_admin_channel(ctx)

    @enable.command(name="cmd", help="Enables a command in current channel.",
                    description="Removes a command from bot's ignore list to enable it in current channel. The command "
                                "name must be the full qualified name of the command without command prefix. If a "
                                "subcommand should be enabled, the command name must be inside quotation marks like "
                                "\"enable cmd\".")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def enable_cmd(self, ctx, command):
        result = self.bot.ignoring.remove_command(command, ctx.channel)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Not_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Command {} is not blocked in this channel".format(command))
        await utils.log_to_admin_channel(ctx)
