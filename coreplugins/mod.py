from datetime import datetime
import platform
import pkgutil
from discord.ext import commands

from conf import Config, Lang
from botutils import utils
from botutils.timeutils import parse_time_input
from botutils.stringutils import paginate
from botutils.converters import get_best_username, convert_member, get_plugin_by_name
from base import BasePlugin, ConfigurableType
import subsystems
from subsystems import help
from subsystems.ignoring import IgnoreEditResult, IgnoreType
from subsystems.presence import PresencePriority


class Plugin(BasePlugin, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self, category=help.DefaultCategories.MOD)

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

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.qualified_name.replace(" ", "_")))

    def command_description(self, command):
        return Lang.lang(self, "desc_{}".format(command.qualified_name.replace(" ", "_")))

    """
    Misc commands
    """

    @commands.command(name="about", aliases=["git", "github"])
    async def about(self, ctx):
        about_msg = Lang.lang(self, 'about_version', Config.VERSION, self.bot.guild.name,
                              platform.system(), platform.release(), platform.version())

        if Config.get(self)['bot_info_link']:
            about_msg += Lang.lang(self, 'about_general_info', Config.get(self)['bot_info_link'])
        about_msg += Lang.lang(self, 'about_repo', Config.get(self).get('repo_link',
                                                                        Lang.lang(self, 'about_no_repo_link')))
        if Config.get(self)['privacy_notes_link']:
            lang = ""
            if Config.get(self)['privacy_notes_lang']:
                lang = " ({})".format(Config.get(self)['privacy_notes_lang'])
            about_msg += Lang.lang(self, 'about_privacy', Config.get(self)['privacy_notes_link'], lang)

        about_msg += Lang.lang(self, 'about_devs', "Costamiri, Fluggs, Gobo77")
        if Config.get(self)['profile_pic_creator']:
            about_msg += Lang.lang(self, 'about_pfp', Config.get(self)['profile_pic_creator'])

        about_msg += Lang.lang(self, 'about_thanks')

        await ctx.send(about_msg)

    """
    Plugin control
    """

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

    @commands.group(name="plugin", invoke_without_command=True)
    async def plugins(self, ctx):
        await ctx.invoke(self.bot.get_command("plugins list"))

    @plugins.command(name="list")
    async def plugins_list(self, ctx):
        coreplugins = [c.name for c in self.bot.plugins if c.type == ConfigurableType.COREPLUGIN]
        plugins = [c.name for c in self.bot.plugins if c.type == ConfigurableType.PLUGIN]
        subsys = []
        for modname in pkgutil.iter_modules(subsystems.__path__):
            subsys.append(modname.name)

        for msg in paginate(coreplugins,
                            prefix=Lang.lang(self, 'plugins_loaded_cp', len(coreplugins)), delimiter=", "):
            await ctx.send(msg)
        for msg in paginate(plugins,
                            prefix=Lang.lang(self, 'plugins_loaded_pl', len(plugins)), delimiter=", "):
            await ctx.send(msg)
        for msg in paginate(subsys,
                            prefix=Lang.lang(self, 'plugins_loaded_ss', len(subsys)), delimiter=", "):
            await ctx.send(msg)

    @plugins.command(name="unload")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def plugins_unload(self, ctx, name):
        instance = get_plugin_by_name(self.bot, name)
        if instance is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "no_plugin_loaded", name))
            return

        if instance.get_configurable_type() != ConfigurableType.PLUGIN:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "coreplugins_cant_unloaded"))
            return

        if self.bot.unload_plugin(name):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "plugin_not_unloadable", name))

    @plugins.command(name="load")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def plugins_load(self, ctx, name):
        instance = get_plugin_by_name(self.bot, name)
        if instance is not None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "plugin_already_loaded", name))
            return

        if self.bot.load_plugin(Config().PLUGIN_DIR, name):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "plugin_not_loadable", name))

    @plugins.command(name="reload")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def plugins_reload(self, ctx, name):
        instance = get_plugin_by_name(self.bot, name)
        if instance is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "no_plugin_loaded", name))
            return

        if instance.get_configurable_type() != ConfigurableType.PLUGIN:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "coreplugins_cant_reloaded"))
            return

        if self.bot.unload_plugin(name, False) and self.bot.load_plugin(Config().PLUGIN_DIR, name):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "errors_on_reload", name))

    """
    Presence subsystem
    """

    @commands.group(name="presence", invoke_without_command=True)
    async def presence(self, ctx):
        await ctx.invoke(self.bot.get_command("presence list"))

    @presence.command(name="list")
    async def presence_list(self, ctx):
        def get_message(item):
            return Lang.lang(self, "presence_entry", item.presence_id + 1, item.message)

        entries = self.bot.presence.filter_messages_list(PresencePriority.LOW)
        if not entries:
            await ctx.send(Lang.lang(self, "no_presences"))
        else:
            for msg in paginate(entries,
                                prefix=Lang.lang(self, "presence_prefix"),
                                f=get_message):
                await ctx.send(msg)

    @presence.command(name="add")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def presence_add(self, ctx, *, message):
        if self.bot.presence.register(message, PresencePriority.LOW) is not None:
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Lang.lang(self, "presence_added_debug", message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_unknown_error"))

    @presence.command(name="del", usage="<id>")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def presence_del(self, ctx, entry_id: int):
        entry_id -= 1
        presence_message = "PANIC"
        if entry_id in self.bot.presence.messages:
            presence_message = self.bot.presence.messages[entry_id].message

        if self.bot.presence.deregister_id(entry_id):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Lang.lang(self, "presence_removed_debug", presence_message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_not_exists", entry_id))

    """
    Ignoring subsystem
    """

    @commands.group(name="disable", invoke_without_command=True, aliases=["ignore", "block"],
                    usage="<full command name>")
    async def disable(self, ctx, *command):
        cmd = " ".join(command)
        if not await self._pre_cmd_checks(ctx.message, cmd):
            return

        result = self.bot.ignoring.add_passive(ctx.author, cmd)
        if result == IgnoreEditResult.Success:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.Already_in_list:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'passive_already_blocked', cmd))
        await utils.log_to_admin_channel(ctx)

    @disable.command(name="mod", usage="[user|command|until]")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def disable_mod(self, ctx, *args):
        user, command, until = await self._parse_mod_args(ctx.message, *args)

        final_msg = "PANIC"
        reaction = Lang.CMDERROR
        until_str = ""

        if until is not None:
            until_str = Lang.lang(self, 'until', until.strftime(Lang.lang(self, 'until_strf')))
        else:
            until = datetime.max

        # disable command in current channel
        if user is None and command is not None:
            result = self.bot.ignoring.add_command(command, ctx.channel, until)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'cmd_blocked', command, until_str)
            elif result == IgnoreEditResult.Already_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'cmd_already_blocked', command)
            elif result == IgnoreEditResult.Until_in_past:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'no_time_machine')

        # disable user completely
        elif user is not None and command is None:
            result = self.bot.ignoring.add_user(user, until)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'user_blocked', get_best_username(user), until_str)
            elif result == IgnoreEditResult.Already_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'user_already_blocked', get_best_username(user))
            elif result == IgnoreEditResult.Until_in_past:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'no_time_machine')

        # disable active command usage for user
        elif user is not None and command is not None:
            result = self.bot.ignoring.add_active(user, command, until)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'active_usage_blocked', get_best_username(user), command, until_str)
            elif result == IgnoreEditResult.Already_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'active_already_blocked', get_best_username(user), command)
            elif result == IgnoreEditResult.Until_in_past:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'no_time_machine')

        # nothing parsed
        else:
            reaction = Lang.CMDERROR
            final_msg = Lang.lang(self, 'member_or_time_not_found')

        await utils.log_to_admin_channel(ctx)
        await ctx.message.add_reaction(reaction)
        await ctx.send(final_msg)

    @disable.command(name="list")
    async def disable_list(self, ctx):
        def get_item_msg(item):
            return item.to_message()

        async def write_list(itype: IgnoreType, prefix):
            ilist = self.bot.ignoring.get_ignore_list(itype)
            if len(ilist) > 0:
                for msg in paginate(ilist, prefix=prefix, f=get_item_msg):
                    await ctx.send(msg)

        if self.bot.ignoring.get_full_ignore_len() < 1:
            await ctx.send(Lang.lang(self, 'nothing_blocked'))
            return

        await write_list(IgnoreType.User, Lang.lang(self, 'list_users'))
        await write_list(IgnoreType.Command, Lang.lang(self, 'list_cmds'))
        await write_list(IgnoreType.Active_Usage, Lang.lang(self, 'list_active'))
        await write_list(IgnoreType.Passive_Usage, Lang.lang(self, 'list_passive'))

    @commands.group(name="enable", invoke_without_command=True, aliases=["unignore", "unblock"],
                    usage="[full command name]")
    async def enable(self, ctx, command=None):
        final_msg = "PANIC"
        reaction = Lang.CMDERROR

        # remove all commands if no command given
        if command is None:
            all_entries = [entry
                           for entry
                           in self.bot.ignoring.get_ignore_list(IgnoreType.Passive_Usage)
                           if entry.user == ctx.author]

            for entry in all_entries:
                self.bot.ignoring.remove(entry)

            reaction = Lang.CMDSUCCESS
            final_msg = Lang.lang(self, 'all_passives_unblocked', command)

        # remove given command
        else:
            result = self.bot.ignoring.remove_passive(ctx.author, command)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
            elif result == IgnoreEditResult.Not_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'passive_not_blocked', command)

        await utils.log_to_admin_channel(ctx)
        await ctx.message.add_reaction(reaction)
        await ctx.send(final_msg)

    @enable.command(name="mod", usage="[user|command]")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def enable_mod(self, ctx, *args):
        user, command, until = await self._parse_mod_args(ctx.message, *args)

        final_msg = "PANIC"
        reaction = Lang.CMDERROR

        # enable command in current channel
        if user is None and command is not None:
            result = self.bot.ignoring.remove_command(command, ctx.channel)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'cmd_unblocked', command)
            elif result == IgnoreEditResult.Not_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'cmd_not_blocked', command)

        # enable user completely
        elif user is not None and command is None:
            result = self.bot.ignoring.remove_user(user)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'user_unblocked', get_best_username(user))
            elif result == IgnoreEditResult.Not_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'user_not_blocked', get_best_username(user))

        # enable active command usage for user
        elif user is not None and command is not None:
            result = self.bot.ignoring.remove_active(user, command)
            if result == IgnoreEditResult.Success:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'active_usage_unblocked', get_best_username(user), command)
            elif result == IgnoreEditResult.Not_in_list:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'active_not_blocked', get_best_username(user), command)

        # nothing parsed
        else:
            reaction = Lang.CMDERROR
            final_msg = Lang.lang(self, 'member_or_time_not_found')

        await utils.log_to_admin_channel(ctx)
        await ctx.message.add_reaction(reaction)
        await ctx.send(final_msg)

    async def _is_valid_command(self, command):
        """
        Checks if the command is a valid and registered, existing command

        :param command: The command
        :return: True if the command is valid and exists
        """
        all_commands = self.bot.all_commands
        customcmds = self.bot.ignoring.get_additional_commands()

        if command in all_commands or command in customcmds:
            return True
        return False

    async def _pre_cmd_checks(self, message, command):
        """
        Some pre-checks for command disabling

        :param message: the message
        :param command: the command to disable
        :return: True if command can be disabled
        """
        if not await self._is_valid_command(command):
            await utils.add_reaction(message, Lang.CMDERROR)
            await message.channel.send(Lang.lang(self, 'cmd_not_found', command))
            return False
        if command == "enable":
            await utils.add_reaction(message, Lang.CMDERROR)
            await message.channel.send(Lang.lang(self, 'enable_cant_blocked'))
            return False
        return True

    async def _parse_mod_args(self, message, *args):
        """
        Parses the input args for valid command names, users and until datetime input

        :param message: the message
        :param args: the arguments
        :return: a tuple of user, command, until with None as value if not found
        """
        user = None
        command = None
        until = None

        for i in range(0, len(args)):
            arg = args[i]

            if user is None:
                try:
                    user = convert_member(self.bot, arg)
                    continue
                except commands.CommandError:
                    pass

            if command is None and await self._is_valid_command(arg):
                if await self._pre_cmd_checks(message, arg):
                    command = arg
                    continue

            if until is None:
                parsed_time = datetime.max
                if len(args) > i + 1:
                    parsed_time = parse_time_input(*args[i:i + 2], end_of_day=True)
                if parsed_time == datetime.max:
                    parsed_time = parse_time_input(arg, end_of_day=True)

                if parsed_time < datetime.max:
                    until = parsed_time
                    continue

        return user, command, until
