import inspect
import re
import random
import logging
import abc
from typing import Optional, Union, Dict, Type, List

from nextcord import User, Message, Member, Embed
from nextcord.ext import commands

from base.configurable import BasePlugin, NotFound
from base.data import Storage, Lang, Config
from botutils import utils, converters, permchecks
from botutils.converters import get_best_username
from botutils.stringutils import paginate
from botutils.utils import add_reaction
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


class CmdEmpty(Exception):
    """
    Flow control, raised by Cmd.delete_by_id() when the cmd is now empty and can be safely deleted.
    """
    pass


class NoPermissions(Exception):
    """
    Flow control, raised by Cmd.delete_by_id() when the delete requester does not have sufficient permission.
    """
    pass


class Cmd(abc.ABC):
    """Base class for text and embed cmds"""

    def __init__(self, plugin, name: str, creator_id: int, aliases: list = None):
        """
        Creates a new custom cmd

        :param plugin: The plugin instance
        :param name: The command name, must be unique, will be lowered
        :param creator_id: The user id of the initial creator of the cmd
        :param aliases: List of command name aliases
        """

        self.plugin = plugin
        self.name = str(name).lower()
        self.creator_id = creator_id
        self._aliases = aliases if aliases else []

    def __eq__(self, other):
        if isinstance(other, TextCmd):
            if other.name == self.name:
                return True
        elif isinstance(other, str):
            if other == self.name:
                return True
            if other in self.aliases:
                return True
        return False

    @property
    def aliases(self):
        return self._aliases

    def add_alias(self, alias):
        self.aliases.append(alias)

    def has_alias(self):
        return len(self.aliases) > 0

    def format_alias(self) -> str:
        """
        :return: "cmd.name (alias1, alias2, alias3)"
        """
        if self.has_alias():
            return "{} ({})".format(self.name, ", ".join(self.aliases))
        return self.name

    def clear_aliases(self):
        self._aliases = []

    @abc.abstractmethod
    def serialize(self) -> dict:
        pass

    @classmethod
    def deserialize(cls, plugin, name: str, d: dict):
        """
        Deserializes any cmd dict to its corresponding cmd class.

        :param plugin: Plugin ref
        :type: Plugin
        :param name: cmd name
        :param d: dictionary that is to be deserialized
        :return: Cmd subclass representing the cmd
        :rtype: Cmd
        """
        cmdtype: Type[Cmd] = plugin.cmd_type_map[d["type"]]
        return cmdtype.deserialize(plugin, name, d)

    @abc.abstractmethod
    async def invoke(self, message: Message, *arguments):
        """
        Invokes the command.

        :param message: Source / Caller message
        :param arguments: Command arguments
        """
        pass

    def has_delete_permission(self, user: Union[User, Member]) -> bool:
        """
        Is called before a full delete of the cmd.

        :param user: User who called the delete command
        :return: Whether `user` is permitted to delete the command.
        """
        return permchecks.check_mod_access(user) or user.id == self.creator_id

    @abc.abstractmethod
    def delete_by_id(self, user: Union[User, Member], del_id: int):
        """
        Called by del on an id. This method is not supposed to call Plugin._save(), the caller is.

        :param user: user who requests the deletion (del command author)
        :param del_id: id to be deleted
        :raises IndexError: del_id not found
        :raises CmdEmpty: The cmd is now empty (last id was deleted) and can now safely be deleted completely
        :raises NoPermission: When `user` does not have sufficient permission to delete the cmd entry.
        """
        pass

    @abc.abstractmethod
    async def cmd_info(self, ctx, *args):
        """
        Handles a cmd info command for this custom command.

        :param ctx: Context to send the response to
        :param args: Command arguments
        """
        pass


class TextCmd(Cmd):
    """Represents a custom text cmd"""

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
        super().__init__(plugin, name, creator_id, aliases=aliases)
        self.author_ids = [author_ids[i] if author_ids is not None else creator_id for i in range(0, len(*texts))]
        self.texts = list(*texts)

    def __len__(self):
        return len(self.texts)

    def serialize(self) -> dict:
        """
        Serializes the cmd data to a dict

        :return: A dict with the creator and texts
        """
        r = {
            'creator': self.creator_id,
            'authors': self.author_ids,
            'texts': self.texts,
            'type': 'text'
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
        :rtype: TextCmd
        """
        return TextCmd(plugin, name, d['creator'], d['texts'],
                       author_ids=d.get('authors', []), aliases=d.get('aliases', None))

    async def invoke(self, message: Message, *arguments):
        assert len(self) > 0
        text_id = random.choice(range(0, len(self)))
        await message.channel.send(self.get_formatted_text(text_id, message, *arguments))

    def add(self, author: User, text: str):
        """
        Adds a command text.

        :param author: Command text author
        :param text: Command text
        """
        to_replace = "/me"
        if text.startswith(to_replace):
            text = "_{}_".format(text[len(to_replace):])
        self.texts.append(text)
        self.author_ids.append(author.id)

    def get_raw_text(self, text_id):
        """
        Returns the raw text with the given ID as formatted string or raise IndexError if ID does exists
        """
        member = converters.get_username_from_id(self.author_ids[text_id])
        if member is None:
            member = Lang.lang(self.plugin, "unknown_user")
        return Lang.lang(self.plugin, 'raw_text', text_id + 1, self.texts[text_id], member)

    def get_raw_texts(self, index=0):
        """
        Returns all raw texts of the cmd as formatted string, beginning with index
        """
        return [self.get_raw_text(i) for i in range(index, len(self.texts))]

    def get_formatted_text(self, text_id: int, msg: Message, *cmd_args: str) -> str:
        """
        Formats and replaces the wildcards of a given text id of the cmd for using it as custom cmd.

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

            if member is not None and Config().bot.ignoring.check_passive_usage(member, self.name):
                raise UserBlockedCommand(member, self.name)
            cmd_content = cmd_content.replace(wildcard, arg)

        return cmd_content

    async def _cmd_raw_single_page(self, ctx, index):
        """
        Assumptions:
        * cmd_name in self.plugin.commands.values()
        * cmd_name is lowercase
        * index exists
        """
        texts = self.get_raw_texts(index=index)
        aliases = self.plugin.format_aliases(self.aliases)
        i = 0
        delimiter = "\n"
        threshold = 1900
        msg = Lang.lang(self.plugin, 'raw_prefix', self.plugin.prefix, self.name,
                        converters.get_username_from_id(self.creator_id),
                        len(self.get_raw_texts()), aliases).strip()
        for el in texts:
            i += 1
            suffix = Lang.lang(self.plugin, "raw_suffix", index + 1, i + index - 1, self.name, index + i)
            if len(msg) + len(delimiter) + len(el) + len(suffix) > threshold:
                msg += suffix
                break

            msg += delimiter + el
        await ctx.send(msg)

    def delete_by_id(self, user, del_id):
        if user.id != self.author_ids[del_id] and user.id != self.creator_id and not permchecks.check_mod_access(user):
            raise NoPermissions
        del self.author_ids[del_id]
        del self.texts[del_id]
        if not self.texts:
            raise CmdEmpty

    async def cmd_info(self, ctx: commands.Context, *args):
        """
        Handles a cmd info command and sends the response to ctx.

        :param ctx: Context
        :param args: Command arguments; first one is interpreted as the index
        """
        # Parse index
        single_page = True  # index != "17++"
        single_text = False  # index == "17"
        if args:
            index = args[0]
            if index.endswith("++"):
                single_page = False
                index = index[:-2]
            elif index.endswith("+"):
                index = index[:-1]
            elif index.lower() == "last":
                index = len(self)
            else:
                single_text = True
            try:
                index = int(index) - 1
            except (ValueError, TypeError):
                await ctx.send(Lang.lang(self.plugin, "text_id_not_positive"))
                return
        else:
            index = 0

        # Error handling
        if index < 0 or index >= len(self):
            await ctx.send(Lang.lang(self.plugin, "text_id_not_found"))
            return

        if single_page and not single_text:
            await self._cmd_raw_single_page(ctx, index)

        else:
            creator = converters.get_best_user(self.creator_id)
            aliases = self.plugin.format_aliases(self.aliases)

            if single_text:
                raw_texts = [self.get_raw_text(index)]
            else:
                raw_texts = self.get_raw_texts(index=index)
            for msg in paginate(raw_texts,
                                delimiter="\n",
                                prefix=Lang.lang(self.plugin,
                                                 'raw_prefix',
                                                 self.plugin.prefix,
                                                 self.name,
                                                 converters.get_best_username(creator),
                                                 len(raw_texts),
                                                 aliases)):
                await ctx.send(msg)


class EmbedField:
    """
    Represents an embed field.
    """
    def __init__(self, plugin: BasePlugin):
        """
        Embed field representation

        :param plugin: Plugin ref
        """
        self.plugin = plugin
        self.title: Optional[str] = None
        self.title_author: Optional[Union[Member, User]] = None
        self.value: Optional[str] = None
        self.value_author: Optional[Union[Member, User]] = None

    def get_title(self):
        return self.title if self.title else Lang.lang(self.plugin, "embed_no_title")

    def get_value(self):
        return self.value if self.value else Lang.lang(self.value, "embed_no_value")

    def is_empty(self):
        """
        :return: Returns whether this field has a title or value set.
        """
        if self.title or self.value:
            return False
        return True

    def format_info(self, index: int):
        """
        Formats this embed field to be used in !cmd info.

        :param index: Index of this embed field within the entire embed cmd
        :return: nicely formatted string
        """
        if self.title:
            title = Lang.lang(self.plugin, "embed_entry", self.title, get_best_username(self.title_author))
        else:
            title = Lang.lang(self.plugin, "embed_no_title")

        if self.value:
            value = Lang.lang(self.plugin, "embed_entry", self.value, get_best_username(self.value_author))
        else:
            value = Lang.lang(self.plugin, "embed_no_value")

        return Lang.lang(self.plugin, "embed_field_info", str(index), title, value)

    def set_title(self, title: str, title_author: Union[Member, User]):
        self.title = title
        self.title_author = title_author

    def set_value(self, value: str, value_author: Union[Member, User]):
        self.value = value
        self.value_author = value_author

    def has_edit_permission(self, user):
        return user in (self.title_author, self.value_author)

    def serialize(self) -> dict:
        """
        Serializes a field.

        :return: Serialized EmbedField
        """
        title = None
        if self.title:
            title = {
                "title": self.title,
                "author_id": self.title_author.id
            }

        value = None
        if self.value:
            value = {
                "value": self.value,
                "author_id": self.value_author.id
            }

        return {
            "title": title,
            "value": value
        }

    @classmethod
    def deserialize(cls, plugin, field_dict: dict):
        """
        Deserializes a field dict.

        :param plugin: Plugin reference
        :type: Plugin
        :param field_dict: field dict as created by serialize()
        :return: EmbedField
        :rtype: EmbedField
        """
        r = cls(plugin)
        title = field_dict["title"]
        if title:
            r.set_title(title["title"], converters.get_best_user(title["author_id"]))
        value = field_dict["value"]
        if value:
            r.set_value(value["value"], converters.get_best_user(value["author_id"]))
        return r


class EmbedCmd(Cmd):
    """
    Represents a custom embed cmd
    """
    def __init__(self, plugin, name: str, creator_id: int,
                 header: str = None, fields: list = None, aliases: list = None):
        super().__init__(plugin, name, creator_id, aliases=aliases)

        self.header: Optional[str] = header
        self.fields = fields if fields else []

    def serialize(self) -> dict:
        r = {
            "creator": self.creator_id,
            "type": "embed"
        }
        if self.fields:
            r["fields"] = [el.serialize() for el in self.fields]
        if self.aliases:
            r["aliases"] = self.aliases
        if self.header:
            r["header"] = self.header
        return r

    @classmethod
    def deserialize(cls, plugin, name: str, d: dict):
        assert d["type"] == "embed"
        header = d.get("header", None)
        fields = d.get("fields", None)
        if fields:
            fields = [EmbedField.deserialize(plugin, el) for el in fields]
        return cls(plugin, name, d["creator"], header=header, fields=fields, aliases=d.get("aliases", None))

    def build_embed(self) -> Optional[Embed]:
        """
        Builds the embed that this cmd represents. Only complete fields (with title and value) are added.
        :return: Embed object if there is at least one complete field; None otherwise
        """
        r = Embed()
        found = False
        if self.header:
            found = True
            r.title = self.header
        for el in self.fields:
            if el.title and el.value:
                found = True
                r.add_field(name=el.title, value=el.value)
        return r if found else None

    async def invoke(self, message: Message, *arguments):
        embed = self.build_embed()
        if embed:
            await message.channel.send(embed=embed)
        else:
            await add_reaction(message, Lang.CMDERROR)
            await message.channel.send(Lang.lang(self.plugin, "embed_error_no_fields"))

    def add_field(self) -> bool:
        """
        Adds an empty field if there is not an empty one yet.

        :return: True if field was added, False otherwise
        """
        # find existing empty field
        for el in self.fields:
            if el.is_empty():
                return False

        self.fields.append(EmbedField(self.plugin))
        return True

    def has_edit_permission(self, user, field_id):
        return self.fields[field_id].has_edit_permission(user) or user.id == self.creator_id \
            or permchecks.check_mod_access(user)

    def delete_by_id(self, user, del_id):
        if not self.has_edit_permission(user, del_id - 1):
            raise NoPermissions
        del self.fields[del_id - 1]
        if not self.header and not self.fields:
            raise CmdEmpty

    async def cmd_info(self, ctx, *args):
        """
        Sends cmd info to ctx

        :param ctx: context
        :param args: arguments passed (ignored)
        """
        creator = get_best_username(converters.get_best_user(self.creator_id))
        aliases = self.plugin.format_aliases(self.aliases)

        entries = []
        for i in range(len(self.fields)):
            entries.append(self.fields[i].format_info(i+1))

        if not entries:
            entries.append(Lang.lang(self.plugin, "embed_info_no_fields"))

        if self.header:
            header = [Lang.lang(self.plugin, "embed_info_header_prefix", self.header)]
            entries = header + entries

        for msg in paginate(entries,
                            delimiter="\n\n",
                            prefix=Lang.lang(self.plugin,
                                             "embed_info_prefix",
                                             self.plugin.prefix,
                                             self.name,
                                             creator,
                                             aliases)):
            await ctx.send(msg)


class Plugin(BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.USER)

        self.cmd_type_map: Dict[str, Type[Cmd]] = {
            "text": TextCmd,
            "embed": EmbedCmd
        }
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
        return {}

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
                new_cmds[cmd_name] = TextCmd(self, cmd_name, 0, [old_config[cmd]]).serialize()

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
        await cmd.invoke(msg, *cmd_args)

    def _find_cmd(self, name) -> Optional[TextCmd]:
        """
        Finds a cmd by name or alias.

        :param name: Cmd name or alias
        :return: Command if found, None otherwise
        """
        for el in self.commands.values():
            if el == name:
                return el
        return None

    def _register_cmd(self, name: str, cmd: Cmd):
        self.commands[name] = cmd
        self.bot.ignoring.add_additional_command(name)
        self._save()

    def format_aliases(self, aliases: List[str]) -> str:
        """
        Formats the display of aliases in a standard manner. Intended for use in cmd info.

        :param aliases: List of cmd aliases
        :return: formatted string that contains the aliases
        """
        if not aliases:
            return ""

        r = []
        for el in aliases:
            r.append("`{}`".format(el))
        return Lang.lang(self, "raw_aliases", ", ".join(r))

    @commands.group(name="cmd", invoke_without_command=True, aliases=["bar"])
    async def cmd(self, ctx):
        await Config().bot.helpsys.cmd_help(ctx, self, ctx.command)

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
                cmds.append(Lang.lang(self, 'list_full_data', prefix, k, len(cmd), max(arg_lens)))

            else:
                cmds.append("{}{}".format(prefix, k))

        if not cmds:
            cmds = [Lang.lang(self, 'list_no_cmds')]

        cmds.sort(key=str.lower)
        cmds = paginate(cmds, delimiter=", ", suffix=suffix)
        return cmds

    @cmd.command(name="list")
    async def cmd_list(self, ctx, full=""):
        if full in self.commands:
            return await ctx.invoke(self.bot.get_command("cmd info"), full)

        cmds = self._format_cmd_list(full=full)

        for msg in cmds:
            await ctx.send(msg)

    @cmd.command(name="info")
    async def cmd_raw(self, ctx, cmd_name, *args):
        cmd_name = cmd_name.lower()
        cmd = self._find_cmd(cmd_name)

        if not cmd:
            await ctx.send(Lang.lang(self, "raw_doesnt_exist", cmd_name))
            return

        await cmd.cmd_info(ctx, *args)

    @cmd.command(name="search")
    async def cmd_search(self, ctx, cmd_name, *args):
        cmd_name = cmd_name.lower()
        if cmd_name not in self.commands.values():
            await ctx.send(Lang.lang(self, "raw_doesnt_exist"))
            return

        found = []
        cmd = self._find_cmd(cmd_name)
        for i in range(len(cmd)):
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

    @cmd.group(name="add", invoke_without_command=True)
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

        cmd = self._find_cmd(cmd_name)
        if isinstance(cmd, TextCmd):
            cmd.add(ctx.author, message)
            self._save()

            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, 'cmd_text_added', cmd.name, message))
            await ctx.send(Lang.lang(self, "add_exists", cmd.name))
            return

        if isinstance(cmd, EmbedCmd):
            await ctx.send(Lang.lang(self, "embed_error_is_embed_cmd"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        if cmd is None:
            cmd = TextCmd(self, cmd_name, ctx.author.id, [])
            cmd.add(ctx.author, message)
            self._register_cmd(cmd_name, cmd)

            await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
            await utils.write_mod_channel(Lang.lang(self, 'cmd_added', cmd_name,
                                                    self.commands[cmd_name].get_raw_texts()))
            return

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

        if text_id is None:
            if not cmd.has_delete_permission(ctx.author):
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                await ctx.send(Lang.lang(self, 'del_perm_missing'))
                return

            # Remove command
            del self.commands[cmd.name]

        else:
            # remove text
            try:
                cmd.delete_by_id(ctx.author, text_id)
            except IndexError:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "text_id_not_found"))
                return
            except CmdEmpty:
                del self.commands[cmd.name]
            except NoPermissions:
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                await ctx.send(Lang.lang(self, 'del_perm_missing'))
                return

        self._save()
        # await utils.log_to_admin_channel(ctx)
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def _assert_embed_cmd(self, ctx, name) -> Optional[EmbedCmd]:
        cmd = self._find_cmd(name)
        if not cmd:
            await ctx.send(Lang.lang(self, "embed_error_cmd_not_found"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return None
        if not isinstance(cmd, EmbedCmd):
            await ctx.send(Lang.lang(self, "embed_error_is_not_embed_cmd"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return None
        return cmd

    @cmd.group(name="embed", invoke_without_command=True)
    async def cmd_embed(self, ctx):
        await Config().bot.helpsys.cmd_help(ctx, self, ctx.command)

    ###
    # cmd embed add command
    ###
    async def handler_add_embed(self, ctx, name: str):
        """
        Creates an embed cmd or adds an empty field.

        :param ctx: cmd call context
        :param name: embed cmd name
        """
        found = self._find_cmd(name)
        # new cmd
        if not found:
            cmd = EmbedCmd(self, name, ctx.author.id)
            cmd.add_field()
            self._register_cmd(name, cmd)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        # wrong cmd
        if not isinstance(found, EmbedCmd):
            # wrong cmd
            await ctx.send(Lang.lang(self, "embed_error_is_not_embed_cmd"))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        # existing cmd
        r = found.add_field()
        if r:
            self._save()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    @cmd_add.command(name="embed", hidden=True)
    async def cmd_add_embed(self, ctx, name: str):
        await self.handler_add_embed(ctx, name)

    @cmd_embed.command(name="add")
    async def cmd_embed_add(self, ctx, name: str):
        await self.handler_add_embed(ctx, name)

    ###
    # cmd embed title/value commands
    ###
    async def _get_embed_field(self, ctx, cmd_name, index) -> Optional[EmbedField]:
        cmd = await self._assert_embed_cmd(ctx, cmd_name)
        if not cmd:
            return None

        try:
            if not cmd.has_edit_permission(ctx.author, index - 1):
                await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
                await ctx.send(Lang.lang(self, "embed_error_no_edit_perms"))
                return None
            return cmd.fields[index - 1]
        except IndexError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "embed_error_field_not_found", index))
            return None

    async def _handler_cmd_embed_title(self, ctx, cmd_name: str, index: int, title):
        field = await self._get_embed_field(ctx, cmd_name, index)
        if not field:
            return

        field.set_title(title, ctx.author)
        self._save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_embed.command(name="title")
    async def cmd_embed_title(self, ctx, cmd_name: str, index: int, *, msg):
        await self._handler_cmd_embed_title(ctx, cmd_name, index, msg)

    @cmd.command(name="title", hidden=True)
    async def cmd_title(self, ctx, cmd_name: str, index: int, *, msg):
        await self._handler_cmd_embed_title(ctx, cmd_name, index, msg)

    async def _handler_cmd_embed_value(self, ctx, cmd_name: str, index: int, value):
        field = await self._get_embed_field(ctx, cmd_name, index)
        if not field:
            return

        field.set_value(value, ctx.author)
        self._save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_embed.command(name="value")
    async def cmd_embed_value(self, ctx, cmd_name: str, index: int, *, msg):
        await self._handler_cmd_embed_value(ctx, cmd_name, index, msg)

    @cmd.command(name="value", hidden=True)
    async def cmd_value(self, ctx, cmd_name: str, index: int, *, msg):
        await self._handler_cmd_embed_value(ctx, cmd_name, index, msg)

    ###
    # cmd embed header command
    ###
    async def _handler_cmd_embed_header(self, ctx, cmd_name: str, msg: Optional[str]):
        cmd = await self._assert_embed_cmd(ctx, cmd_name)
        if not cmd:
            return None

        # include msg == " " etc
        if msg is None or not msg.strip():
            msg = None

        if not cmd.has_delete_permission(ctx.author):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self, "embed_error_no_header_perms"))
            return

        cmd.header = msg
        self._save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_embed.command(name="header")
    async def cmd_embed_header(self, ctx, cmd_name, *, msg: Optional[str]):
        await self._handler_cmd_embed_header(ctx, cmd_name, msg)

    @cmd.command(name="header", hidden=True)
    async def cmd_header(self, ctx, cmd_name, *, msg: Optional[str]):
        await self._handler_cmd_embed_header(ctx, cmd_name, msg)

    ###
    # cmd embed swap command
    ###
    async def _handler_cmd_embed_swap(self, ctx, cmd_name: str, index1: int, index2: int):
        cmd = await self._assert_embed_cmd(ctx, cmd_name)
        if not cmd:
            return

        # Assert fields exist
        not_found = index1
        try:
            field1 = cmd.fields[index1 - 1]
            not_found = index2
            field2 = cmd.fields[index2 - 1]
        except IndexError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "embed_error_field_not_found", not_found))
            return

        # permissions: has to be author of at least one field title/value or cmd author
        if not cmd.has_edit_permission(ctx.author, index1 - 1) and not cmd.has_edit_permission(ctx.author, index2 - 1):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            await ctx.send(Lang.lang(self, "embed_error_no_edit_perms"))
            return

        cmd.fields[index1 - 1] = field2
        cmd.fields[index2 - 1] = field1
        self._save()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_embed.command(name="swap")
    async def cmd_embed_swap(self, ctx, cmd_name: str, index1: int, index2: int):
        await self._handler_cmd_embed_swap(ctx, cmd_name, index1, index2)

    @cmd.command(name="swap", hidden=True)
    async def cmd_swap(self, ctx, cmd_name: str, index1: int, index2: int):
        await self._handler_cmd_embed_swap(ctx, cmd_name, index1, index2)

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

        c.clear_aliases()
        self._save()
        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd.command(name="random", aliases=["rnd", "rng"])
    async def cmd_random(self, ctx, *args):
        candidates = []
        weights = []
        for el in self.commands.values():
            if isinstance(el, TextCmd):
                candidates.append(el)
                weights.append(len(el.texts))

        if not candidates:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        cmd = random.choices(candidates, weights=weights)[0]
        await cmd.invoke(ctx.message, *args)

    @cmd.command(name="image", aliases=["randomimage"])
    async def cmd_image(self, ctx):
        candidates = []
        for el in self.commands.values():
            if not isinstance(el, TextCmd):
                continue

            for text in el.texts:
                if text.startswith("http"):
                    candidates.append(text)

        if not candidates:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        await ctx.send(random.choice(candidates))
