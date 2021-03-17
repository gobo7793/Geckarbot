import platform
from datetime import datetime

from discord.ext import commands
from discord.ext.commands import MemberConverter, UserConverter

from base import BasePlugin, ConfigurableType
from botutils import utils
from botutils.converters import get_best_username, get_plugin_by_name
from botutils.stringutils import paginate
from botutils.timeutils import parse_time_input
from data import Config, Lang
from subsystems.help import DefaultCategories
from subsystems.ignoring import IgnoreEditResult, IgnoreType
from subsystems.presence import PresencePriority


class Plugin(BasePlugin, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self, category=DefaultCategories.MOD)

        # Move commands to help category 'user'
        for cmd in self.get_commands():
            if cmd.name in ["presence", "about"]:
                self.bot.helpsys.default_category(DefaultCategories.USER).add_command(cmd)
                self.bot.helpsys.default_category(DefaultCategories.MOD).remove_command(cmd)

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

    #####
    # Misc commands
    #####

    @commands.command(name="about", aliases=["git", "github"])
    async def cmd_about(self, ctx):
        about_msg = Lang.lang(self, 'about_version', self.bot.VERSION, self.bot.guild.name,
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

    #####
    # Plugin control
    #####

    @commands.group(name="plugin", aliases=["plugins"], invoke_without_command=True)
    async def cmd_plugins(self, ctx):
        await ctx.invoke(self.bot.get_command("plugin list"))

    @cmd_plugins.command(name="list")
    async def cmd_plugins_list(self, ctx):
        coreplugins = self.bot.get_coreplugins()
        plugins = self.bot.get_normalplugins()
        subsys = self.bot.get_subsystem_list()

        msgs = [
            "{}\n{}".format(Lang.lang(self, 'plugins_loaded_ss', len(subsys)), ", ".join(subsys)),
            "{}\n{}".format(Lang.lang(self, 'plugins_loaded_cp', len(coreplugins)), ", ".join(coreplugins)),
            "{}\n{}".format(Lang.lang(self, 'plugins_loaded_pl', len(plugins)), ", ".join(plugins))
        ]

        for msg in paginate(msgs, delimiter="\n\n"):
            await ctx.send(msg)

    @cmd_plugins.command(name="available", aliases=["unloaded", "disabled"])
    async def cmd_plugins_avail(self, ctx):
        avail = self.bot.get_unloaded_plugins()

        if avail:
            await ctx.send("{}\n{}".format(Lang.lang(self, 'plugins_avail', len(avail)), ", ".join(avail)))
        else:
            await ctx.send(Lang.lang(self, 'no_plugin_avail'))

    @cmd_plugins.command(name="unload", aliases=["disable"])
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_plugins_unload(self, ctx, name):
        instance = get_plugin_by_name(name)
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

    @cmd_plugins.command(name="load", aliases=["enable"])
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_plugins_load(self, ctx, name):
        instance = get_plugin_by_name(name)
        if instance is not None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "plugin_already_loaded", name))
            return

        if self.bot.load_plugin(self.bot.PLUGIN_DIR, name):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "plugin_not_loadable", name))

    @cmd_plugins.command(name="reload")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_plugins_reload(self, ctx, name):
        instance = get_plugin_by_name(name)
        if instance is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "no_plugin_loaded", name))
            return

        if instance.get_configurable_type() != ConfigurableType.PLUGIN:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "coreplugins_cant_reloaded"))
            return

        if self.bot.unload_plugin(name, False) and self.bot.load_plugin(self.bot.PLUGIN_DIR, name):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "errors_on_reload", name))

    #####
    # Presence Subsystem
    #####

    @commands.group(name="presence", invoke_without_command=True)
    async def cmd_presence(self, ctx):
        await ctx.invoke(self.bot.get_command("presence list"))

    @cmd_presence.command(name="list")
    async def cmd_presence_list(self, ctx):
        def get_message(item):
            return Lang.lang(self, "presence_entry", item.presence_id, item.message)

        entries = self.bot.presence.filter_messages_list(PresencePriority.LOW)
        if not entries:
            await ctx.send(Lang.lang(self, "no_presences"))
        else:
            for msg in paginate(entries,
                                prefix=Lang.lang(self, "presence_prefix", len(entries)),
                                f=get_message):
                await ctx.send(msg)

    @cmd_presence.command(name="add")
    # @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_presence_add(self, ctx, *, message):
        if self.bot.presence.register(message, PresencePriority.LOW) is not None:
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, "presence_added_debug", message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_unknown_error"))

    @cmd_presence.command(name="del", usage="<id>")
    # @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_presence_del(self, ctx, entry_id: int):
        presence_message = "PANIC"
        if entry_id in self.bot.presence.messages:
            presence_message = self.bot.presence.messages[entry_id].message

        if self.bot.presence.deregister_id(entry_id):
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, "presence_removed_debug", presence_message))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "presence_not_exists", entry_id))

    #####
    # Ignoring Subsystem
    #####

    @commands.group(name="disable", invoke_without_command=True, aliases=["ignore", "block"],
                    usage="<full command name>")
    async def cmd_disable(self, ctx, *, command):
        if not await self._pre_cmd_checks(ctx.message, command):
            return

        cmd = self._get_full_cmd_name(command)

        result = self.bot.ignoring.add_passive(ctx.author, cmd)
        if result == IgnoreEditResult.SUCCESS:
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
        elif result == IgnoreEditResult.ALREADY_IN_LIST:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'passive_already_blocked', cmd))
        await utils.log_to_mod_channel(ctx)

    @cmd_disable.command(name="mod", usage="[user|command|until]")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_disable_mod(self, ctx, *args):
        user, command, until = await self._parse_mod_args(ctx, *args)
        if user == -1 or command == -1 or until == -1:
            return

        final_msg = None
        reaction = Lang.CMDERROR
        until_str = ""

        if until is not None:
            until_str = Lang.lang(self, 'until', until.strftime(Lang.lang(self, 'until_strf')))
        else:
            until = datetime.max

        # disable command in current channel
        if user is None and command is not None:
            result = self.bot.ignoring.add_command(command, ctx.channel, until)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'cmd_blocked', command, until_str)
            elif result == IgnoreEditResult.ALREADY_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'cmd_already_blocked', command)
            elif result == IgnoreEditResult.UNTIL_IN_PAST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'no_time_machine')

        # disable user completely
        elif user is not None and command is None:
            if user.id == ctx.author.id:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'cant_block_yourself')
            else:
                result = self.bot.ignoring.add_user(user, until)
                if result == IgnoreEditResult.SUCCESS:
                    reaction = Lang.CMDSUCCESS
                    final_msg = Lang.lang(self, 'user_blocked', get_best_username(user), until_str)
                elif result == IgnoreEditResult.ALREADY_IN_LIST:
                    reaction = Lang.CMDERROR
                    final_msg = Lang.lang(self, 'user_already_blocked', get_best_username(user))
                elif result == IgnoreEditResult.UNTIL_IN_PAST:
                    reaction = Lang.CMDERROR
                    final_msg = Lang.lang(self, 'no_time_machine')

        # disable active command usage for user
        elif user is not None and command is not None:
            result = self.bot.ignoring.add_active(user, command, until)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'active_usage_blocked', get_best_username(user), command, until_str)
            elif result == IgnoreEditResult.ALREADY_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'active_already_blocked', get_best_username(user), command)
            elif result == IgnoreEditResult.UNTIL_IN_PAST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'no_time_machine')

        # nothing parsed
        else:
            reaction = Lang.CMDERROR
            final_msg = Lang.lang(self, 'member_or_time_not_found')

        await utils.log_to_mod_channel(ctx)
        await utils.add_reaction(ctx.message, reaction)
        if final_msg is not None:
            await ctx.send(final_msg)

    @cmd_disable.command(name="list")
    async def cmd_disable_list(self, ctx):
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

        await write_list(IgnoreType.USER, Lang.lang(self, 'list_users'))
        await write_list(IgnoreType.COMMAND, Lang.lang(self, 'list_cmds'))
        await write_list(IgnoreType.ACTIVE_USAGE, Lang.lang(self, 'list_active'))
        await write_list(IgnoreType.PASSIVE_USAGE, Lang.lang(self, 'list_passive'))

    @commands.group(name="enable", invoke_without_command=True, aliases=["unignore", "unblock"],
                    usage="[full command name]")
    async def cmd_enable(self, ctx, *, command=None):
        final_msg = None
        reaction = Lang.CMDERROR

        # remove all commands if no command given
        if command is None:
            all_entries = [entry
                           for entry
                           in self.bot.ignoring.get_ignore_list(IgnoreType.PASSIVE_USAGE)
                           if entry.user == ctx.author]

            for entry in all_entries:
                self.bot.ignoring.remove(entry)

            reaction = Lang.CMDSUCCESS
            final_msg = Lang.lang(self, 'all_passives_unblocked')

        # remove VALID given command
        elif self._is_valid_command(command):
            cmd = self._get_full_cmd_name(command)
            result = self.bot.ignoring.remove_passive(ctx.author, cmd)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
            elif result == IgnoreEditResult.NOT_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'passive_not_blocked', cmd)

        # command not valid
        else:
            reaction = Lang.CMDERROR
            final_msg = Lang.lang(self, 'cmd_not_found', command)

        await utils.log_to_mod_channel(ctx)
        await utils.add_reaction(ctx.message, reaction)
        if final_msg is not None:
            await ctx.send(final_msg)

    @cmd_enable.command(name="mod", usage="[user|command]")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_enable_mod(self, ctx, *args):
        user, command, _ = await self._parse_mod_args(ctx, *args)

        final_msg = None
        reaction = Lang.CMDERROR

        # enable command in current channel
        if user is None and command is not None:
            result = self.bot.ignoring.remove_command(command, ctx.channel)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'cmd_unblocked', command)
            elif result == IgnoreEditResult.NOT_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'cmd_not_blocked', command)

        # enable user completely
        elif user is not None and command is None:
            result = self.bot.ignoring.remove_user(user)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'user_unblocked', get_best_username(user))
            elif result == IgnoreEditResult.NOT_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'user_not_blocked', get_best_username(user))

        # enable active command usage for user
        elif user is not None and command is not None:
            result = self.bot.ignoring.remove_active(user, command)
            if result == IgnoreEditResult.SUCCESS:
                reaction = Lang.CMDSUCCESS
                final_msg = Lang.lang(self, 'active_usage_unblocked', get_best_username(user), command)
            elif result == IgnoreEditResult.NOT_IN_LIST:
                reaction = Lang.CMDERROR
                final_msg = Lang.lang(self, 'active_not_blocked', get_best_username(user), command)

        # nothing parsed
        else:
            reaction = Lang.CMDERROR
            final_msg = Lang.lang(self, 'member_or_time_not_found')

        await utils.log_to_mod_channel(ctx)
        await utils.add_reaction(ctx.message, reaction)
        if final_msg is not None:
            await ctx.send(final_msg)

    def _get_full_cmd_name(self, command):
        """
        Returns the full qualified command name for native commands or it's custom command name.
        Doesn't check if command name is valid.

        :param command: The command
        :return: The command name
        """
        native_cmd = self.bot.get_command(command)
        if native_cmd is not None:
            return native_cmd.qualified_name
        return command

    def _is_valid_command(self, command):
        """
        Checks if the command is a valid and registered, existing command

        :param command: The command
        :return: True if the command is valid and exists
        """
        native = self.bot.get_command(command)
        customcmds = self.bot.ignoring.get_additional_commands()

        if native is not None or command in customcmds:
            return True
        return False

    async def _pre_cmd_checks(self, message, command):
        """
        Some pre-checks for command disabling including output to the channel of the message

        :param message: the message
        :param command: the command to disable
        :return: True if command can be disabled
        """
        if not self._is_valid_command(command):
            await utils.add_reaction(message, Lang.CMDERROR)
            await message.channel.send(Lang.lang(self, 'cmd_not_found', command))
            return False
        if self._get_full_cmd_name(command) == "enable":
            await utils.add_reaction(message, Lang.CMDERROR)
            await message.channel.send(Lang.lang(self, 'enable_cant_blocked'))
            return False
        return True

    async def _parse_mod_args(self, ctx, *args):
        """
        Parses the input args for valid command names, users and until datetime input.

        :param ctx: the command context
        :param args: the arguments
        :return: a tuple of user, command, until.
         If a valid value can be found, the value will be returned for each tuple element.
         If a value can't be found, None will be returned for each tuple element.
         If a value has an invalid value, -1 for this value will be returned if a
          sub-check already did an output to the channel or -2 otherwise for each tuple element.
        """
        user = None
        command = None
        until = None

        for i in range(0, len(args)):
            arg = args[i]

            if user is None:
                try:
                    user = await MemberConverter().convert(ctx, arg)
                    continue
                except commands.CommandError:
                    try:
                        user = await UserConverter().convert(ctx, arg)
                        continue
                    except commands.CommandError:
                        pass

            if command is None and self._is_valid_command(arg):
                if await self._pre_cmd_checks(ctx.message, arg):
                    command = self._get_full_cmd_name(arg)
                else:
                    command = -1
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
