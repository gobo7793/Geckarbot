import inspect
import re
import random
import logging
from typing import Optional

import discord
from discord.ext import commands

from base.configurable import BasePlugin, NotFound
from data import Storage, Lang, Config
from botutils import utils, converters, permchecks
from botutils.stringutils import paginate
from services.ignoring import UserBlockedCommand
from services.helpsys import DefaultCategories

WILDCARD_USER = "%u"
WILDCARD_UMENTION = "%um"
WILDCARD_ALL_ARGS = "%a"

QUOTATION_SIGNS = "\"‘‚‛“„‟⹂「」『』〝〞﹁﹂﹃﹄＂｢｣«»‹›《》〈〉"
cmd_re = re.compile(rf"\+?([{QUOTATION_SIGNS}]([^{QUOTATION_SIGNS}]*)[{QUOTATION_SIGNS}]|\S+)")
arg_list_re = re.compile(r"(%(\d)(\*?))")
mention_re = re.compile(r"<[@!#&]{0,2}\d+>")


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

    def __init__(self, plugin, name: str, creator_id: int, *texts, author_ids: list = None, aliases: list = None):
        """
        Creates a new custom cmd

        :param plugin: The plugin instance
        :param name: The command name, must be unique, will be lowered
        :param creator_id: The user id of the initial creator of the cmd
        :param texts: The output texts of the cmd
        :param author_ids: The author ids for the output texts
        :param aliases: List of command name aliases
        """

        self.plugin = plugin
        self.name = str(name).lower()
        self.creator_id = creator_id
        self.author_ids = [author_ids[i] if author_ids is not None else creator_id for i in range(0, len(*texts))]
        self.texts = list(*texts)
        self.aliases = aliases

    def __eq__(self, other):
        if isinstance(other, Cmd):
            if other.name == self.name:
                return True
        elif isinstance(other, str):
            if other == self.name:
                return True
            if other in self.get_aliases():
                return True
        return False

    def serialize(self) -> dict:
        """
        Serializes the cmd data to a dict

        :return: A dict with the creator and texts
        """
        r = {
            'creator': self.creator_id,
            'authors': self.author_ids,
            'texts': self.texts
        }
        if self.aliases:
            r['aliases'] = self.aliases
        return r

    @classmethod
    def deserialize(cls, plugin, name: str, d: dict):
        """
        Constructs a Cmd object from a dict.

        :param plugin: The plugin instance
        :type plugin: Plugin
        :param name: The command name
        :param d: dict made by serialize()
        :return: Cmd object
        :rtype: Cmd
        """
        return Cmd(plugin, name, d['creator'], d['texts'],
                   author_ids=d.get('authors', []), aliases=d.get('aliases', None))

    def get_aliases(self):
        if self.aliases:
            return self.aliases
        return []

    def get_raw_text(self, text_id):
        """Returns the raw text with the given ID as formatted string or raise IndexError if ID not exists"""
        member = converters.get_username_from_id(self.author_ids[text_id])
        if member is None:
            member = Lang.lang(self.plugin, "unknown_user")
        return Lang.lang(self.plugin, 'raw_text', text_id + 1, self.texts[text_id], member)

    def get_raw_texts(self, index=0):
        """Returns all raw texts of the cmd as formatted string, beginning with index"""
        return [self.get_raw_text(i) for i in range(index, len(self.texts))]

    def get_formatted_text(self, bot, text_id: int, msg: discord.Message, cmd_args: list) -> str:
        """
        Formats and replaces the wildcards of a given text id of the cmd for using it as custom cmd.

        :param bot: The bot
        :type bot: class:`Geckarbot.Geckarbot`
        :param text_id: The text id
        :param msg: The original message
        :param cmd_args: The used command arguments
        :returns: The formatted command text
        :raises UserBlockedCommand: If a mentioned user has the command on its ignore list
        """

        cmd_content = self.texts[text_id]

        # general replaces
        cmd_content = cmd_content.replace(WILDCARD_UMENTION, msg.author.mention)
        cmd_content = cmd_content.replace(WILDCARD_USER, converters.get_best_username(msg.author))

        if WILDCARD_ALL_ARGS in cmd_content:
            cmd_content = cmd_content.replace(WILDCARD_ALL_ARGS, _get_all_arg_str(0, cmd_args))

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
                member = converters.convert_member(arg)
            except commands.BadArgument:
                member = None

            if member is not None and bot.ignoring.check_passive_usage(member, self.name):
                raise UserBlockedCommand(member, self.name)
            cmd_content = cmd_content.replace(wildcard, arg)

        return cmd_content

    def get_ran_formatted_text(self, bot, msg: discord.Message, cmd_args: list) -> str:
        """
        Formats and replaces the wildcards of a random text of the cmd for using it as custom cmd.
        If a mentioned user has the command on its ignore list, a UserBlockedCommand error will be raised.

        :param bot: The bot
        :type bot: class:`Geckarbot.Geckarbot`
        :param msg: The original message
        :param cmd_args: The used command arguments
        :returns: The formatted command text
        """

        text_len = len(self.texts)
        if text_len > 0:
            text_id = random.choice(range(0, text_len))
            return self.get_formatted_text(bot, text_id, msg, cmd_args)
        return ""

    def add_alias(self, alias):
        if self.aliases is None:
            self.aliases = []
        self.aliases.append(alias)

    def has_alias(self):
        return bool(self.aliases)

    def format_alias(self) -> str:
        """
        :return: "cmd.name (alias1, alias2, alias3)"
        """
        if self.has_alias():
            return "{} ({})".format(self.name, ", ".join(self.aliases))
        return self.name


class Plugin(BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.USER)

        self.prefix = Config.get(self)['prefix']
        self.commands = {}

        self._load()

    @commands.Cog.listener()
    async def on_message(self, msg):
        if (msg.content.startswith(self.prefix)
                and msg.author.id != self.bot.user.id
                and not self.bot.ignoring.check_user(msg.author)
                and permchecks.debug_user_check(msg.author)):
            await self._process_message(msg)

    def default_config(self, container=None):
        return {
            "cfgversion": 3,
            "prefix": "+",
            "guidelines": "https://github.com/gobo7793/Geckarbot/wiki/Command-Guidelines"
        }

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
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

    async def command_help(self, ctx, command):
        if not command.name == "cmd":
            raise NotFound

        # Command / category help
        msg = [
            self.bot.helpsys.format_usage(command, plugin=self) + "\n",
            Lang.lang(self, "desc_cmd") + "\n",
        ]
        msg += self.bot.helpsys.format_subcmds(ctx, self, command)

        # Custom command list
        msg.append("\n" + Lang.lang(self, "help_custom_cmd_list_prefix"))
        msg += self._format_cmd_list(incl_prefix=True)

        for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
            await ctx.send(msg)

    def command_help_string(self, command):
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

    # def command_usage(self, command):
    #     if command.name == "search":
    #         return Lang.lang(self, "help_search_usage")
    #     else:
    #         raise NotFound()
    #
    # def command_description(self, command):
    #     if command.name == "info":
    #         return Lang.lang(self, "help_info_options")
    #     elif command.name == "search":
    #         return Lang.lang(self, "help_search_desc")
    #     else:
    #         raise NotFound()

    def _load(self):
        """Loads the commands"""
        # Update from old config versions
        if "_prefix" in Storage.get(self):
            self._update_config_from_1_to_2(Storage.get(self))
        elif "_prefix" in Config.get(self):
            self._update_config_from_1_to_2(Config.get(self))

        if Config.get(self)['cfgversion'] == 2:
            self._update_config_from_2_to_3()

        # actually load the commands
        for k in Storage.get(self).keys():
            self.commands[str(k)] = Cmd.deserialize(self, k, Storage.get(self)[k])
            self.bot.ignoring.add_additional_command(k)

    def _save(self):
        """Saves the commands to the storage and the plugin config"""
        cmd_dict = {}
        for k, cmd in self.commands.items():
            cmd_dict[k] = cmd.serialize()

        Storage.set(self, cmd_dict)
        Storage.save(self)

        Config.save(self)

    def _update_config_from_2_to_3(self):
        """Updates the configuration from version 2 to version 3 (adding authors for output texts)"""
        logging.info("Update Custom CMD config from version 2 to version 3")

        for cmd in Storage.get(self).values():
            cmd['authors'] = [0 for _ in range(0, len(cmd['texts']))]

        Config.get(self)['cfgversion'] = 3
        Storage.save(self)
        Config.save(self)
        logging.info("Converting finished.")

    def _update_config_from_1_to_2(self, old_config):
        """
        Updates the configuration from version 1 (indicator: contains '_prefix') to version 2 (split Config/Storage)

        :param old_config: the old config dict
        """
        logging.info("Update Custom CMD config from version 1 to version 2")

        new_config = self.default_config()
        new_config['prefix'] = old_config['_prefix']

        logging.info("Converting %d custom commands...", len(old_config) - 1)
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

    async def _process_message(self, msg):
        """Will be called from on_message listener to react for custom cmds"""

        # get cmd parts/args
        msg_args = cmd_re.findall(msg.content[len(self.prefix):])
        if len(msg_args) < 1:
            return
        cmd_name = msg_args[0][1].lower() if msg_args[0][1] else msg_args[0][0].lower()

        cmd_args = msg_args[1:]
        if cmd_name not in self.commands.values():
            return
        if (self.bot.ignoring.check_command_name(cmd_name, msg.channel)
                or self.bot.ignoring.check_passive_usage(msg.author, cmd_name)):
            raise commands.DisabledCommand()

        cmd = self._find_cmd(cmd_name)
        assert cmd
        cmd_content = cmd.get_ran_formatted_text(self.bot, msg, cmd_args)

        await msg.channel.send(cmd_content)

    def _find_cmd(self, name) -> Optional[Cmd]:
        """
        Finds a cmd by name or alias.

        :param name: Cmd name or alias
        :return: Command if found, None otherwise
        """
        for el in self.commands.values():
            if el == name:
                return el
        return None

    @commands.group(name="cmd", invoke_without_command=True, aliases=["bar"])
    async def cmd(self, ctx):
        await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd.command(name="prefix")
    async def cmd_prefix(self, ctx, new_prefix=None):
        # get current prefix
        if new_prefix is None:
            example = random.choice(list(self.commands.keys()))
            await ctx.send(Lang.lang(self, 'current_prefix', Config.get(self)['prefix'], example))
            return

        # set new prefix
        if not permchecks.check_mod_access(ctx.author):
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            raise commands.BotMissingAnyRole(Config().ADMIN_ROLES)

        if new_prefix == ctx.prefix:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_prefix'))
        else:
            Config.get(self)['prefix'] = new_prefix
            self._save()
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    def _format_cmd_list(self, full="", incl_prefix=False):
        cmds = []
        suffix = Lang.lang(self, 'list_suffix') if full else ""
        prefix = self.prefix if incl_prefix else ""

        for k, cmd in self.commands.items():
            if full:
                arg_lens = []
                for t in cmd.texts:
                    arg_list = arg_list_re.findall(str(t))
                    arg_lens.append(len(arg_list))
                cmds.append(Lang.lang(self, 'list_full_data', prefix, k, len(cmd.texts), max(arg_lens)))

            else:
                cmds.append("{}{}".format(prefix, k))

        if not cmds:
            cmds = [Lang.lang(self, 'list_no_cmds')]

        cmds.sort(key=str.lower)
        cmds = paginate(cmds, delimiter=", ", suffix=suffix)
        return cmds

    @cmd.command(name="list")
    async def cmd_list(self, ctx, full=""):
        if full in self.commands.keys():
            return await ctx.invoke(self.bot.get_command("cmd info"), full)

        cmds = self._format_cmd_list(full=full)

        for msg in cmds:
            await ctx.send(msg)

    async def _cmd_raw_single_page(self, ctx, cmd_name, index):
        """
        Assumptions:
        * cmd_name in self.commands.values()
        * cmd_name is lowercase
        * index exists
        """
        cmd = self._find_cmd(cmd_name)
        texts = cmd.get_raw_texts(index=index)
        aliases = ""
        if cmd.aliases:
            aliases = Lang.lang(self, "raw_aliases", ", ".join(cmd.aliases))
        i = 0
        delimiter = "\n"
        threshold = 1900
        msg = Lang.lang(self, 'raw_prefix', self.prefix, cmd.name,
                        converters.get_username_from_id(cmd.creator_id),
                        len(cmd.get_raw_texts()), aliases).strip()
        for el in texts:
            i += 1
            suffix = Lang.lang(self, "raw_suffix", index + 1, i + index - 1, cmd_name, index + i)
            if len(msg) + len(delimiter) + len(el) + len(suffix) > threshold:
                msg += suffix
                break

            msg += delimiter + el
        await ctx.send(msg)

    @cmd.command(name="info")
    async def cmd_raw(self, ctx, cmd_name, index=None):
        cmd_name = cmd_name.lower()
        cmd = self._find_cmd(cmd_name)

        # Parse index
        single_page = True  # index != "17++"
        single_text = False  # index == "17"
        if index is not None:
            if index.endswith("++"):
                single_page = False
                index = index[:-2]
            elif index.endswith("+"):
                index = index[:-1]
            elif index.lower() == "last":
                index = len(cmd.texts)
            else:
                single_text = True
            try:
                index = int(index) - 1
            except (ValueError, TypeError):
                await ctx.send(Lang.lang(self, "text_id_not_positive"))
                return
        else:
            index = 0

        # Error handling
        if not cmd:
            await ctx.send(Lang.lang(self, "raw_doesnt_exist", cmd_name))
            return
        if index < 0 or index >= len(cmd.texts):
            await ctx.send(Lang.lang(self, "text_id_not_found"))
            return

        if single_page and not single_text:
            await self._cmd_raw_single_page(ctx, cmd_name, index)

        else:
            creator = converters.get_best_user(cmd.creator_id)
            aliases = ""
            if cmd.aliases:
                aliases = Lang.lang(self, "raw_aliases", ", ".join(aliases))

            if single_text:
                raw_texts = [cmd.get_raw_text(index)]
            else:
                raw_texts = cmd.get_raw_texts(index=index)
            for msg in paginate(raw_texts,
                                delimiter="\n",
                                prefix=Lang.lang(self,
                                                 'raw_prefix',
                                                 self.prefix,
                                                 cmd.name,
                                                 converters.get_best_username(creator),
                                                 len(raw_texts),
                                                 aliases)):
                await ctx.send(msg)

    @cmd.command(name="search")
    async def cmd_search(self, ctx, cmd_name, *args):
        cmd_name = cmd_name.lower()
        if cmd_name not in self.commands.values():
            await ctx.send(Lang.lang(self, "raw_doesnt_exist"))
            return

        found = []
        cmd = self._find_cmd(cmd_name)
        for i in range(len(cmd.texts)):
            text = cmd.texts[i]
            hit = False
            for term in args:
                if term.lower() in text.lower():
                    hit = True
                else:
                    hit = False
                    break
            if hit:
                found.append(cmd.get_raw_text(i))

        # Output
        if len(found) == 0:
            await ctx.send(Lang.lang(self, "search_empty"))
        else:
            for msg in paginate(found, prefix=Lang.lang(self, "search_prefix")):
                await ctx.send(msg)

    @cmd.command(name="guidelines")
    async def cmd_guidelines(self, ctx):
        await ctx.send("<{}>".format(Config.get(self)['guidelines']))

    @cmd.command(name="add")
    async def cmd_add(self, ctx, cmd_name, *, message: str):
        if not message:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['message'])
        cmd_name = cmd_name.lower()

        if mention_re.match(cmd_name) is not None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'no_mention_allowed'))
            return

        if not cmd_name:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            return

        # TODO Process multiple output texts
        cmd_texts = [message]
        text_authors = [ctx.author.id for _ in range(0, len(cmd_texts))]

        # Process special discord /cmd
        for i in range(0, len(cmd_texts)):
            contains_me = cmd_texts[i].lower().startswith("/me")

            if contains_me:
                cmd_texts[i] = "_{}_".format(cmd_texts[i][3:])

        cmd = self._find_cmd(cmd_name)
        if cmd:
            cmd.texts.extend(cmd_texts)
            cmd.author_ids.extend(text_authors)
            self._save()
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, 'cmd_text_added', cmd.name, cmd_texts))
            await ctx.send(Lang.lang(self, "add_exists", cmd.name))
        else:
            self.commands[cmd_name] = Cmd(self, cmd_name, ctx.author.id, cmd_texts)
            self.bot.ignoring.add_additional_command(cmd_name)
            self._save()
            # await utils.log_to_admin_channel(ctx)
            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, 'cmd_added', cmd_name,
                                                    self.commands[cmd_name].get_raw_texts()))

    # @cmd.command(name="edit")
    async def cmd_edit(self, ctx, cmd_name, *args):
        if not "".join(args):
            raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['args'])

        text_id = None
        try:
            text_id = int(args[0])
        except ValueError:
            pass

        arg_text = " ".join(args)
        if text_id is None:
            await ctx.invoke(self.bot.get_command("cmd del"), cmd_name)
            await ctx.invoke(self.bot.get_command("cmd add"), cmd_name, arg_text)
        else:
            await ctx.invoke(self.bot.get_command("cmd del"), cmd_name, text_id)
            await ctx.invoke(self.bot.get_command("cmd add"), cmd_name, arg_text)

    @cmd.command(name="del")
    async def cmd_del(self, ctx, cmd_name, text_id: int = None):
        cmd_name = cmd_name.lower()
        if text_id is not None:
            text_id -= 1

        cmd = self._find_cmd(cmd_name)
        if not cmd:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "del_doesnt_exist", cmd_name))
            return

        if text_id is not None and text_id < 0:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_positive'))
            return

        if text_id is not None and text_id >= len(cmd.texts):
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_found'))
            return

        if text_id is None or (text_id is not None and ctx.author.id != cmd.author_ids[text_id]):
            if ctx.author.id != cmd.creator_id:
                if not permchecks.check_mod_access(ctx.author):
                    await ctx.send(Lang.lang(self, 'del_perm_missing'))
                    return

        if text_id == 0 and len(cmd.texts) == 1:
            text_id = None

        if text_id is None:
            # Remove command
            cmd_raw = cmd.get_raw_texts()
            del self.commands[cmd.name]
            for msg in paginate(cmd_raw, prefix=Lang.lang(self, 'cmd_removed', cmd_name)):
                await utils.write_mod_channel(msg)

        else:
            # remove text
            cmd_raw = cmd.get_raw_text(text_id)
            del cmd.author_ids[text_id]
            del cmd.texts[text_id]
            await utils.write_mod_channel(Lang.lang(self, 'cmd_text_removed', cmd_name, cmd_raw))

        self._save()
        # await utils.log_to_admin_channel(ctx)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def list_aliases(self, ctx):
        """
        Lists all commands that have aliases to ctx.

        :param ctx: Context
        """
        msgs = []
        for el in self.commands.values():
            if el.has_alias():
                msgs.append(el.format_alias())
        for msg in paginate(msgs, delimiter=", "):
            await ctx.send(msg)

    @cmd.command(name="alias")
    async def cmd_alias(self, ctx, *args):
        if len(args) == 0:
            await self.list_aliases(ctx)
            return
        if len(args) > 2:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "alias_too_many_args"))
            return
        if len(args) < 2:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "alias_not_enough_args"))
            return

        # parse args
        existing = None
        alias = None
        for arg in args:
            c = self._find_cmd(arg)
            if c is not None:
                existing = c
            else:
                alias = arg

        if not existing:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "alias_not_found", args[0], args[1]))
            return
        if not alias:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "alias_exists", args[0], args[1]))
            return

        existing.add_alias(alias)
        self._save()
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd.command(name="aliasclear")
    async def cmd_clear_alias(self, ctx, cmd):
        c = self._find_cmd(cmd)
        if c is None:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)
            return

        c.aliases = None
        self._save()
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
