import inspect
import re
import random
import logging

import discord
from discord.ext import commands

from base import BasePlugin, NotFound
from conf import Storage, Lang, Config
from botutils import utils, converters, permchecks
from botutils.stringutils import paginate
from subsystems.ignoring import UserBlockedCommand
from subsystems.help import HelpCategory

wildcard_user = "%u"
wildcard_umention = "%um"
wildcard_all_args = "%a"

quotation_signs = "\"‘‚‛“„‟⹂「」『』〝〞﹁﹂﹃﹄＂｢｣«»‹›《》〈〉"
cmd_re = re.compile(rf"\+?([{quotation_signs}]([^{quotation_signs}]*)[{quotation_signs}]|\S+)")
arg_list_re = re.compile(r"(%(\d)(\*?))")


def _get_all_arg_str(start_index, all_arg_list):
    """
    Concats all args in all_arg_list starting on start_index with space to one string.
    The all_arg_list must be created with the regex pattern cmd_arg_regex_pattern.
    """
    arg = ""
    for j in range(start_index, len(all_arg_list)):
        arg_num = j
        arg = "{} {}".format(
            arg, all_arg_list[arg_num][1] if all_arg_list[arg_num][1] else all_arg_list[arg_num][0])
    return arg.strip()


class Cmd:
    """Represents a custom cmd"""

    def __init__(self, plugin, name: str, creator_id: int, *texts, author_ids: list = None):
        """
        Creates a new custom cmd

        :param plugin: The plugin instance
        :param name: The command name, must be unique, will be lowered
        :param creator_id: The user id of the initial creator of the cmd
        :param texts: The output texts of the cmd
        :param author_ids: The author ids for the output texts
        """

        self.plugin = plugin
        self.name = str(name).lower()
        self.creator_id = creator_id
        self.author_ids = [author_ids[i] if author_ids is not None else creator_id for i in range(0, len(*texts))]
        self.texts = list(*texts)

    def serialize(self):
        """
        Serializes the cmd data to a dict

        :return: A dict with the creator and texts
        """
        return {
            'creator': self.creator_id,
            'authors': self.author_ids,
            'texts': self.texts
        }

    @classmethod
    def deserialize(cls, plugin, name, d: dict):
        """
        Constructs a Cmd object from a dict.

        :param plugin: The plugin instance
        :param name: The command name
        :param d: dict made by serialize()
        :return: Cmd object
        """
        return Cmd(plugin, name, d['creator'], d['texts'], author_ids=d.get('authors', []))

    def get_raw_text(self, text_id):
        """Returns the raw text with the given ID as formatted string or raise IndexError if ID not exists"""
        return Lang.lang(self.plugin, 'raw_text', text_id + 1, self.texts[text_id],
                         converters.get_best_username(self.plugin.bot.get_user(self.author_ids[text_id])))

    def get_raw_texts(self):
        """Returns all raw texts of the cmd as formatted string"""
        return [self.get_raw_text(i) for i in range(0, len(self.texts))]

    async def get_formatted_text(self, bot, text_id: int, msg: discord.Message, cmd_args: list):
        """
        Formats and replaces the wildcards of a given text id of the cmd for using it as custom cmd.
        If a mentioned user has the command on its ignore list, a UserBlockedCommand error will be raised.

        :param bot: The bot
        :param text_id: The text id
        :param msg: The original message
        :param cmd_args: The used command arguments
        :returns: The formatted command text
        """

        cmd_content = self.get_raw_text(text_id)

        # general replaces
        cmd_content = cmd_content.replace(wildcard_umention, msg.author.mention)
        cmd_content = cmd_content.replace(wildcard_user, converters.get_best_username(msg.author))

        if wildcard_all_args in cmd_content:
            cmd_content = cmd_content.replace(wildcard_all_args, _get_all_arg_str(0, cmd_args))

        all_args_positions = arg_list_re.findall(cmd_content)

        # if only one argument in cmd text and no arg given: mention the user
        if len(all_args_positions) == 1 and len(cmd_args) == 0:
            cmd_args = [(msg.author.mention, "")]

        # numbered arguments
        for i in range(0, len(all_args_positions)):
            if i >= len(cmd_args):
                break

            # Replace args
            wildcard = all_args_positions[i][0]
            arg_num = int(all_args_positions[i][1]) - 1
            arg = cmd_args[arg_num][1] if cmd_args[arg_num][1] else cmd_args[arg_num][0]  # [1] = args inside ""

            # All following args
            if all_args_positions[i][2]:
                arg += " " + _get_all_arg_str(i + 1, cmd_args)

            # Ignoring, passive user command blocking
            try:
                member = await converters.convert_member(bot, msg, arg)
            except commands.BadArgument:
                member = None

            if member is not None and bot.ignoring.check_passive_usage(member, self.name):
                raise UserBlockedCommand(member, self.name)
            cmd_content = cmd_content.replace(wildcard, arg)

        return cmd_content

    async def get_ran_formatted_text(self, bot, msg: discord.Message, cmd_args: list):
        """
        Formats and replaces the wildcards of a random text of the cmd for using it as custom cmd.
        If a mentioned user has the command on its ignore list, a UserBlockedCommand error will be raised.

        :param bot: The bot
        :param msg: The original message
        :param cmd_args: The used command arguments
        :returns: The formatted command text
        """

        text_len = len(self.texts)
        if text_len > 0:
            text_id = random.choice(range(0, text_len))
            return self.get_formatted_text(bot, text_id, msg, cmd_args)
        return ""


class CustomCMDHelpCategory(HelpCategory):
    def __init__(self, plugin):
        self.plugin = plugin
        super().__init__("CustomCMD")

    async def send_category_help(self, ctx):
        # Command / category help
        msg = [
            Lang.lang(self.plugin, "help_help") + "\n",
            Lang.lang(self.plugin, "help_cmd_list_prefix"),
        ]
        msg += self.plugin.bot.helpsys.flattened_plugin_help(self.plugin)

        # Custom command list
        msg.append("")
        msg.append(Lang.lang(self.plugin, "help_custom_cmd_list_prefix"))
        msg += self.plugin.format_cmd_list(incl_prefix=True)

        for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)


class Plugin(BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        self.help_category = CustomCMDHelpCategory(self)
        bot.register(self, self.help_category)

        self.prefix = Config.get(self)['prefix']
        self.commands = {}

        self.load()

        @bot.listen()
        async def on_message(msg):
            if (msg.content.startswith(self.prefix)
                    and msg.author.id != self.bot.user.id
                    and not self.bot.ignoring.check_user(msg.author)
                    and permchecks.whitelist_check(msg.author)):
                await self.on_message(msg)

    def default_config(self):
        return {
            "cfgversion": 3,
            "prefix": "+",
            "guidelines": "https://github.com/gobo7793/Geckarbot/wiki/Command-Guidelines"
        }

    def default_storage(self):
        return {
            'fail': {
                "creator": 0,
                "authors": [0],
                "texts": ["_lacht %1 für den Fail aus ♥_"]
            },
            'liebe': {
                "creator": 0,
                "authors": [0],
                "texts": ["https://www.youtube.com/watch?v=TfmJPDmaQdg"]
            },
            'passierschein': {
                "creator": 0,
                "authors": [0],
                "texts": ["Eintragung einer Galeere? Oh, da sind Sie hier falsch! "
                          "Wenden Sie sich an die Hafenkommandantur unten im Hafen.\n"
                          "https://youtu.be/lIiUR2gV0xk"]
            },
            'ping': {
                "creator": 0,
                "authors": [0, 0],
                "texts": ["Pong", "🏓"]
            },
        }

    def load(self):
        """Loads the commands"""
        # Update from old config versions
        if "_prefix" in Storage.get(self):
            self.update_config_from_1_to_2(Storage.get(self))
        elif "_prefix" in Config.get(self):
            self.update_config_from_1_to_2(Config.get(self))

        if Config.get(self)['cfgversion'] == 2:
            self.update_config_from_2_to_3()

        # actually load the commands
        for k in Storage.get(self).keys():
            self.commands[str(k)] = Cmd.deserialize(self, k, Storage.get(self)[k])
            self.bot.ignoring.add_additional_command(k)

    def save(self):
        """Saves the commands to the storage and the plugin config"""
        cmd_dict = {}
        for k in self.commands:
            cmd_dict[k] = self.commands[k].serialize()

        Storage.set(self, cmd_dict)
        Storage.save(self)

        Config.save(self)

    def update_config_from_2_to_3(self):
        """Updates the configuration from version 2 to version 3 (adding authors for output texts)"""
        logging.info("Update Custom CMD config from version 2 to version 3")

        for cmd in Storage.get(self).values():
            cmd['authors'] = [0 for i in range(0, len(cmd['texts']))]

        Config.get(self)['cfgversion'] = 3
        Storage.save(self)
        Config.save(self)
        logging.info("Converting finished.")

    def update_config_from_1_to_2(self, old_config):
        """
        Updates the configuration from version 1 (indicator: contains '_prefix') to version 2 (split Config/Storage)

        :param old_config: the old config dict
        """
        logging.info("Update Custom CMD config from version 1 to version 2")

        new_config = self.default_config()
        new_config['prefix'] = old_config['_prefix']

        logging.info(f"Converting {len(old_config) - 1} custom commands...")
        new_cmds = {}
        for cmd in old_config.keys():
            if cmd == '_prefix':
                continue
            cmd_name = cmd.lower()

            if cmd_name in new_cmds:
                new_cmds[cmd_name]['texts'].append(old_config[cmd])
            else:
                new_cmds[cmd_name] = Cmd(self, cmd_name, 0, [old_config[cmd]]).serialize()

        Storage.set(self, new_cmds)
        Config.save(self)
        Storage.save(self)
        logging.info("Converting finished.")

    async def on_message(self, msg):
        """Will be called from on_message listener to react for custom cmds"""

        # get cmd parts/args
        msg_args = cmd_re.findall(msg.content)
        cmd_name = msg_args[0][1].lower() if msg_args[0][1] else msg_args[0][0].lower()

        cmd_args = msg_args[1:]
        if cmd_name not in self.commands:
            return
        elif (self.bot.ignoring.check_command_name(cmd_name, msg.channel)
              or self.bot.ignoring.check_passive_usage(msg.author, cmd_name)):
            raise commands.DisabledCommand()

        cmd_content = await self.commands[cmd_name].get_ran_formatted_text(self.bot, msg, cmd_args)

        await msg.channel.send(cmd_content)

    async def command_help(self, ctx, command):
        if not command.name == "cmd":
            raise NotFound

        await self.help_category.send_category_help(ctx)

    @commands.group(name="cmd", invoke_without_command=True, aliases=["bar"],
                    help="Adds, list or (for admins) removes a custom command",
                    description="Adds, list or removes a custom command. Custom commands can be added and removed in "
                                "runtime. To use a custom command, the message must start with the setted prefix, "
                                "which can be returned using the prefix subcommand.\n"
                                "More info about adding commands, see !help cmd add.")
    async def cmd(self, ctx):
        await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd.command(name="prefix", help="Returns or sets the prefix",
                 description="Returns or sets the custom command prefix. Only admins can set a new prefix which "
                             "mustn't be the same like for regular commands.")
    async def cmd_prefix(self, ctx, new_prefix=None):
        # get current prefix
        if new_prefix is None:
            example = random.choice(list(self.commands.keys()))
            await ctx.send(Lang.lang(self, 'current_prefix', Config.get(self)['prefix'], example))
            return

        # set new prefix
        if not permchecks.check_full_access(ctx.author):
            await ctx.message.add_reaction(Lang.CMDERROR)
            raise commands.BotMissingAnyRole(Config().FULL_ACCESS_ROLES)

        if new_prefix == ctx.prefix:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_prefix'))
        else:
            Config.get(self)['prefix'] = new_prefix
            self.save()
            await ctx.message.add_reaction(Lang.CMDSUCCESS)

    def format_cmd_list(self, full="", incl_prefix=False):
        cmds = []
        suffix = Lang.lang(self, 'list_suffix') if full else ""
        prefix = self.prefix if incl_prefix else ""

        for k in self.commands.keys():
            if full:
                arg_lens = []
                for t in self.commands[k].texts:
                    arg_list = arg_list_re.findall(t)
                    arg_lens.append(len(arg_list))
                cmds.append(Lang.lang(self, 'list_full_data', prefix, k, len(self.commands[k].texts), max(arg_lens)))

            else:
                cmds.append("{}{}".format(prefix, k))

        if not cmds:
            cmds = [Lang.lang(self, 'list_no_cmds')]

        cmds.sort(key=str.lower)
        cmds = paginate(cmds, delimiter=", ", suffix=suffix)
        return cmds

    @cmd.command(name="list", help="Lists all custom commands.",
                 descripton="Lists all custom commands. Argument full gives more information about the commands.")
    async def cmd_list(self, ctx, full=""):
        cmds = self.format_cmd_list(full=full)

        for msg in cmds:
            await ctx.send(msg)

    @cmd.command(name="info", help="Gets full info about a command")
    async def cmd_raw(self, ctx, cmd_name):
        cmd_name = cmd_name.lower()
        if cmd_name in self.commands:
            creator = self.bot.get_user(self.commands[cmd_name].creator_id)
            for msg in paginate(self.commands[cmd_name].get_raw_texts(),
                                delimiter="\n",
                                prefix=Lang.lang(self,
                                                 'raw_prefix',
                                                 self.prefix,
                                                 cmd_name,
                                                 converters.get_best_username(creator))):
                await ctx.send(msg)
        else:
            await ctx.send(Lang.lang(self, "raw_doesnt_exists", cmd_name))

    @cmd.command(name="guidelines", help="Returns the link to the general command guidelines")
    async def cmd_guidelines(self, ctx):
        # await ctx.send("MAKE BETTER; <https://github.com/gobo7793/Geckarbot/wiki/Command-Guidelines>")
        await ctx.send("<{}>".format(Config.get(self)['guidelines']))

    @cmd.command(name="add", help="Adds a custom command or text", usage="<cmd name> <text...>",
                 description="Adds a custom command or a new output text for an existing command. "
                             "Following wildcards can be used, which will be replaced on using:\n"
                             "%u: The user who uses the command\n"
                             "%um: Mentions the user who uses the command\n"
                             "%n: The nth command argument\n"
                             "%n*: The nth and all following arguments\n"
                             "%a: Alias for %1*\n\n"
                             "Supports /me. If a picture should be added, a URL is required. "
                             "Custom commands must be compliant to the general command guidelines, "
                             "which can be accessed via !cmd guidelines.\n"
                             "Example: !cmd add test Argument1: %1 from user %u\n")
    async def cmd_add(self, ctx, cmd_name, *, args: str):
        if not args:
            await ctx.message.add_reaction(Lang.CMDERROR)
            raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['args'])
        cmd_name = cmd_name.lower()

        # TODO Process multiple output texts
        cmd_texts = [args]
        text_authors = [ctx.author.id for i in range(0, len(cmd_texts))]

        # Process special discord /cmd
        for i in range(0, len(cmd_texts)):
            contains_me = cmd_texts[i].lower().startswith("/me")

            if contains_me:
                cmd_texts[i] = "_{}_".format(cmd_texts[i][3:])

        if cmd_name in self.commands:
            self.commands[cmd_name].texts.extend(cmd_texts)
            self.commands[cmd_name].author_ids.extend(text_authors)
            self.save()
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Lang.lang(self, 'cmd_text_added', cmd_name, cmd_texts))
            await ctx.send(Lang.lang(self, "add_exists", cmd_name))
        else:
            self.commands[cmd_name] = Cmd(self, cmd_name, ctx.author.id, cmd_texts)
            self.bot.ignoring.add_additional_command(cmd_name)
            self.save()
            # await utils.log_to_admin_channel(ctx)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Lang.lang(self, 'cmd_added', cmd_name,
                                                                self.commands[cmd_name].get_raw_texts()))

    # @cmd.command(name="edit")
    # async def cmd_edit(self, ctx, cmd_name, *args):
    #     if not "".join(args):
    #         raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['args'])
    #
    #     text_id = None
    #     try:
    #         text_id = int(args[0])
    #     except ValueError:
    #         pass
    #
    #     arg_text = " ".join(args)
    #     if text_id is None:
    #         await ctx.invoke(self.bot.get_command(f"cmd del"), cmd_name)
    #         await ctx.invoke(self.bot.get_command(f"cmd add"), cmd_name, arg_text)
    #     else:
    #         await ctx.invoke(self.bot.get_command(f"cmd del"), cmd_name, text_id)
    #         await ctx.invoke(self.bot.get_command(f"cmd add"), cmd_name, arg_text)

    @cmd.command(name="del", help="Deletes a custom command or output text",
                 description="Deletes a custom command or one of its output texts. If the last output text was "
                             "deleted, the whole command will be removed. To delete a output text, "
                             "the ID of the text must be given. The IDs and creator can be get via "
                             "!cmd info <command>. Only the original command creator or admins can delete commands "
                             "or its texts.")
    async def cmd_del(self, ctx, cmd_name, text_id: int = None):
        cmd_name = cmd_name.lower()
        if text_id is not None:
            text_id -= 1

        if cmd_name not in self.commands:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "del_doesnt_exists", cmd_name))
            return

        cmd = self.commands[cmd_name]

        if text_id is not None and text_id < 0:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_positive'))
            return

        if text_id is not None and text_id >= len(cmd.texts):
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_exists'))
            return

        if text_id is None or (text_id is not None and ctx.author.id != cmd.author_ids[text_id]):
            if ctx.author.id != cmd.creator_id:
                if not permchecks.check_full_access(ctx.author):
                    await ctx.send(Lang.lang(self, 'del_perm_missing'))
                    return

        if text_id == 0 and len(cmd.texts) == 1:
            text_id = None

        if text_id is None:
            # Remove command
            cmd_raw = cmd.get_raw_texts()
            del (self.commands[cmd_name])
            for msg in paginate(cmd_raw, prefix=Lang.lang(self, 'cmd_removed', cmd_name)):
                await utils.write_debug_channel(self.bot, msg)

        else:
            # remove text
            cmd_raw = cmd.get_raw_text(text_id)
            del (cmd.author_ids[text_id])
            del (cmd.texts[text_id])
            await utils.write_debug_channel(self.bot, Lang.lang(self, 'cmd_text_removed', cmd_name, cmd_raw))

        self.save()
        # await utils.log_to_admin_channel(ctx)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
