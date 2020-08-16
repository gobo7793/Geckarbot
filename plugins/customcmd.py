import inspect
import re
import random

import discord
from discord.ext import commands

from base import BasePlugin
from conf import Storage, Lang, Config
from botutils import utils, converter, permChecks
from subsystems.ignoring import UserBlockedCommand


wildcard_user = "%u"
wildcard_umention = "%um"
wildcard_all_args = "%a"
cmd_arg_regex_pattern = "\\+?(\"([^\"]*)\"|\\S+)"

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

    def __init__(self, name: str, creator_id: int, *texts):
        """
        Creates a new custom cmd

        :param name: The command name, must be unique, will be lowered
        :param creator_id: The user id of the initial creator of the cmd
        :param texts: The output texts of the cmd
        """

        self.name = name.lower()
        self.creator_id = creator_id
        self.texts = list(texts)

    def serialize(self):
        """
        Serializes the cmd data to a dict

        :return: A dict with the creator and texts
        """
        return {
            'creator': self.creator_id,
            'texts': self.texts
        }

    @classmethod
    def deserialize(cls, name, d):
        """
        Constructs a Cmd object from a dict.

        :param name: The command name
        :param d: dict made by serialize()
        :return: Cmd object
        """
        return Cmd(name, d['creator'], d['texts'])

    @classmethod
    def convert_from_1x_format(cls, k, v):
        """Converts a command from the old format with only one """

    def get_ran_raw_text(self):
        """Returns a random text of the cmd or an empty string if the cmd has no text"""
        if len(self.texts) > 0:
            return random.choice(self.texts)
        return ""

    def get_raw_text(self, text_id):
        """Returns the raw text with the given ID as formatted string or raise IndexError if ID not exists"""
        return "#{}: {}".format(text_id, self.texts[text_id])

    def get_raw_texts(self):
        """Returns all raw texts of the cmd as formatted string"""
        if len(self.texts) == 1:
            return [self.get_raw_text(0)]
        else:
            return [self.get_raw_text(i) for i in range(0, len(self.texts))]

    async def get_ran_formatted_text(self, bot, msg: discord.Message, *cmd_args):
        """
        Formats and replaces the wildcard of a random text of the cmd for using it as custom cmd.
        If a mentioned user has the command on its ignore list, a UserBlockedCommand error will be raised.

        :param bot: The bot
        :param msg: The original message
        :param cmd_args: The used command arguments
        :returns: The formatted command text
        """

        cmd_content = self.get_ran_raw_text()

        # general replaces
        cmd_content = cmd_content.replace(wildcard_umention, msg.author.mention)
        cmd_content = cmd_content.replace(wildcard_user, utils.get_best_username(msg.author))

        if wildcard_all_args in cmd_content:
            cmd_content = cmd_content.replace(wildcard_all_args, _get_all_arg_str(0, cmd_args))

        # numbered arguments
        all_args_positions = arg_list_re.findall(cmd_content)
        for i in range(0, len(all_args_positions)):
            if i >= len(cmd_args):
                break

            # Replace args
            wildcard = all_args_positions[i][0]
            arg_num = int(all_args_positions[i][1]) - 1
            arg = cmd_args[arg_num][1] if cmd_args[arg_num][1] else cmd_args[arg_num][0]

            # All following args
            if all_args_positions[i][2]:
                arg += " " + _get_all_arg_str(i + 1, cmd_args)

            # Ignoring, passive user command blocking
            try:
                member = await converter.convert_member(bot, msg, arg)
            except commands.BadArgument:
                member = None

            if member is not None and bot.ignoring.check_user_command(member, self.name):
                raise UserBlockedCommand(member, self.name)
            cmd_content = cmd_content.replace(wildcard, arg)

        return cmd_content


class Plugin(BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.cmd_re = re.compile(cmd_arg_regex_pattern)
        self.prefix = Config.get(self)['prefix']
        self.commands = {}

        self.load()

        @bot.listen()
        async def on_message(msg):
            if (msg.content.startswith(self.prefix)
                    and msg.author.id != self.bot.user.id
                    and not self.bot.ignoring.check_user(msg.author)
                    and permChecks.whitelist_check(msg.author)):
                await self.on_message(msg)

    # def default_config(self):
    #     return {
    #         prefix_key: '+',  # TODO: MOVE TO CONFIG
    #         'liebe': {
    #             "creator": 0,
    #             "texts": ["https://www.youtube.com/watch?v=TfmJPDmaQdg"]
    #         },
    #         'passierschein': {
    #             "creator": 0,
    #             "texts": ["Eintragung einer Galeere? Oh, da sind Sie hier falsch! "
    #                     "Wenden Sie sich an die Hafenkommandantur unten im Hafen.\n"
    #                     "https://youtu.be/lIiUR2gV0xk"]
    #         },
    #         'ping': {
    #             "creator": 0,
    #             "texts": ["Pong"]
    #         },
    #     }

    def load(self):
        """Loads the commands"""
        for k in Storage.get(self).keys():
            self.commands[k] = Cmd.deserialize(k, Storage.get(self)[k])

    def save(self):
        """Saves the commands to the storage"""
        cmd_dict = {}
        for k in self.commands:
            cmd_dict[k.name] = k.serialize()

        Storage.set(self, cmd_dict)
        Storage.save(self)

    async def on_message(self, msg):
        """Will be called from on_message listener to react for custom cmds"""

        # get cmd parts/args
        msg_args = self.cmd_re.findall(msg.content)
        cmd_name = msg_args[0][1].lower() if msg_args[0][1] else msg_args[0][0].lower()

        cmd_args = msg_args[1:]
        if cmd_name not in self.commands:
            return
        elif (self.bot.ignoring.check_command_name(cmd_name, msg.channel)
              or self.bot.ignoring.check_user_command(msg.author, cmd_name)):
            raise commands.DisabledCommand()

        cmd_content = await self.commands[cmd_name].get_ran_formatted_text(self.bot, msg, cmd_args)

        await msg.channel.send(cmd_content)

    @commands.group(name="cmd", invoke_without_command=True, alias="bar",
                    help="Adds, list or (for admins) removes a custom command",
                    description="Adds, list or removes a custom command. Custom commands can be added and removed in "
                                "runtime. To use a custom command, the message must start with the setted prefix, "
                                "which can be returned using the prefix subcommand.")
    async def cmd(self, ctx):
        await ctx.send_help(self.cmd)

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
        if not permChecks.check_full_access(ctx.author):
            await ctx.message.add_reaction(Lang.CMDERROR)
            raise commands.BotMissingAnyRole(Config().FULL_ACCESS_ROLES)

        if new_prefix == ctx.prefix:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'invalid_prefix'))
        else:
            Config.get(self)['prefix'] = new_prefix
            Storage.save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @cmd.command(name="list", help="Lists all custom commands.",
                 descripton="Lists all custom commands. Argument full gives more information of the commands.")
    async def cmd_list(self, ctx, full=""):
        cmds = []
        suffix = Lang.lang(self, 'list_suffix') if full else ""

        for k in self.commands.keys():
            if full:
                arg_lens = []
                for t in self.commands[k].texts:
                    arg_list = arg_list_re.findall(t)
                    arg_lens.append(len(arg_list))
                cmds.append(Lang.lang(self, 'list_full_data', k, len(self.commands[k].texts.max(arg_lens))))

            else:
                cmds.append(k)

        if not cmds:
            await ctx.send(Lang.lang(self, 'list_no_cmds'))
            return

        cmds.sort(key=str.lower)
        cmd_msgs = utils.paginate(cmds, delimiter=", ", suffix=suffix)
        for msg in cmd_msgs:
            await ctx.send(msg)

    @cmd.command(name="raw", help="Gets the raw custom command text")
    async def cmd_raw(self, ctx, cmd_name):
        cmd_name = cmd_name.lower()
        if cmd_name in self.commands:
            creator = self.bot.get_user(self.commands[cmd_name].creator)
            for msg in utils.paginate(self.commands[cmd_name].get_raw_texts(), delimiter="\n",
                                      prefix=Lang.lang(self, 'raw_prefix',
                                                       self.prefix, cmd_name, utils.get_best_username(creator))):
                await ctx.send(msg)
        else:
            await ctx.send(Lang.lang(self, "raw_doesnt_exists", cmd_name))

    @cmd.command(name="guidelines", help="Returns the link to the general command guidelines")
    async def cmd_guidelines(self, ctx):
        # await ctx.send("MAKE BETTER; <https://github.com/gobo7793/Geckarbot/wiki/Command-Guidelines>")
        await ctx.send("<{}>".format(Config.get(self)['guidelines']))

    @cmd.command(name="add", help="Adds a custom command", usage="cmd_name text...",
                 description="Adds a custom command. Following wildcards can be used, which will be replaced on "
                             "using:\n"
                             "%u: The user who uses the command\n"
                             "%um: Mentions the user who uses the command\n"
                             "%n: The nth command argument\n"
                             "%n*: The nth and all following arguments\n"
                             "%a: Alias for %1*\n\n"
                             "Supports /me. Custom commands must be compliant to the general command guidelines, which "
                             "can be found at https://github.com/gobo7793/Geckarbot/wiki/Command-Guidelines.\n"
                             "Example: !cmd add test Argument1: %1 from user %u\n")
    async def cmd_add(self, ctx, cmd_name, *args):
        if not args:
            await ctx.message.add_reaction(Lang.CMDERROR)
            raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['args'])
        cmd_name = cmd_name.lower()

        # TODO Process multiple output texts
        cmd_texts = [" ".join(args)]

        # Process special discord /cmd
        for i in range(0, len(cmd_texts)):
            contains_me = cmd_texts[i].lower().startswith("/me")

            if contains_me:
                cmd_texts[i] = "_{}_".format(cmd_texts[i][3:])

        if cmd_name in self.commands:
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await ctx.send(Lang.lang(self, "add_exists", cmd_name))
        else:
            self.commands[cmd_name] = Cmd(cmd_name, ctx.author.id, cmd_texts)
            self.save()
            # await utils.log_to_admin_channel(ctx)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            await utils.write_debug_channel(self.bot,
                                            Lang.lang(self, 'cmd_added', self.commands[cmd_name].get_raw_texts()))

    @cmd.command(name="del", help="Deletes a custom command or output text",
                 description="Deletes a custom command or one of its output texts. To delete a output text,"
                             "the ID of the text must be given. The IDs and creator can be get via !cmd raw <command>."
                             "Only the original command creator or admins can delete commands or its texts.")
    async def cmd_del(self, ctx, cmd_name, text_id: int = None):
        cmd_name = cmd_name.lower()

        if cmd_name not in self.commands:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "del_doesnt_exists", cmd_name))
            return

        cmd = self.commands[cmd_name]

        if not permChecks.check_full_access(ctx.author) and ctx.author.id != cmd.creator_id:
            await ctx.send(Lang.lang(self, 'del_perm_missing'))
            return

        if text_id is not None and text_id < 0:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_positive'))
            return

        if text_id is not None and text_id >= len(cmd.texts):
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, 'text_id_not_exists'))

        if text_id is None:
            # Remove command
            cmd_raw = cmd.get_raw_texts()
            del (self.commands[cmd_name])
            await utils.write_debug_channel(self.bot, Lang.lang(self, 'cmd_removed', cmd_raw))

        else:
            # remove text
            cmd_raw = cmd.get_raw_text(text_id)
            cmd.texts.remove(text_id)
            await utils.write_debug_channel(self.bot, Lang.lang(self, 'cmd_text_removed', cmd_raw))

        self.save()
        # await utils.log_to_admin_channel(ctx)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
