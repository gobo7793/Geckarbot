import inspect
import re
import random

from discord.ext import commands

from base import BasePlugin
from conf import Config
from botutils import utils, converter, permChecks


lang = {
    'en': {
        'raw_doesnt_exists': "A command \"{}\" doesn't exists, but you can create it!",
        'del_doesnt_exists': "Command \"{}\" can't be deleted, because it doesn't exists...",
        'add_exists': "A command \"{}\" already exists.",
        'list_no_cmds': "I don't know any custom commands :frowning:",
        'cmd_added': "Added custom command: {}",
        'cmd_removed': "Added custom command: {}",
        'invalid_prefix': "The prefix can't be the same like for regular commands.",
        'user_blocked': "The user {} has blocked the command.",
        'current_prefix': "The current prefix for custom commands is: {0}\nExample: {0}{1}",
    },
    'de': {
        'raw_doesnt_exists': "Ein Benutzer-Kommando \"{}\" existiert nicht, erstell es doch einfach selbst!",
        'del_doesnt_exists': "Das Benutzer-Kommando \"{}\" kann nicht gelöscht werden weil es nicht existiert...",
        'add_exists': "Ein Benutzer-Kommando \"{}\" existiert bereits.",
        'list_no_cmds': "Ich kenne keine Benutzer-Kommandos :frowning:",
        'cmd_added': "Benutzer-Kommando hinzugefügt: {}",
        'cmd_removed': "Benutzer-Kommando gelöscht: {}",
        'invalid_prefix': "Das Prefix kann nicht das gleiche wie für normale Benutzer-Kommandos sein.",
        'user_blocked': "{} hat das Benutzer-Kommando geblockt.",
        'current_prefix': "Das aktuelle Präfix für Benutzer-Kommandos ist: {0}\nBeispiel: {0}{1}",
    }
}


prefix_key = "_prefix"
wildcard_user = "%u"
wildcard_umention = "%um"
wildcard_regex_pattern = "(%(\\d)(\\*?))"
cmd_arg_regex_pattern = "(\"([^\"]*)\"|\\S+)"


class Plugin(BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.cmd_re = re.compile(cmd_arg_regex_pattern)
        self.arg_list_re = re.compile(wildcard_regex_pattern)
        self.prefix = self.conf()[prefix_key]

        @bot.listen()
        async def on_message(msg):
            if (msg.content.startswith(self.prefix)
                    and msg.author.id != self.bot.user.id
                    and not self.bot.ignoring.check_user(msg.author)):
                await self.on_message(msg)

    def default_config(self):
        return {
            prefix_key: '+',
            'ping': 'Pong!',
            'nico': '***N I C O   A U F S   M A U L !***   :right_facing_fist_tone1::cow:',
            'passierschein': 'Eintragung einer Galeere? Oh, da sind Sie hier falsch! Wenden Sie sich an die '
                             'Hafenkommandantur unten im Hafen.\n'
                             'https://youtu.be/lIiUR2gV0xk',
            'kris': 'mood <:kristoph:717524523662180383>',
            'slap': "_slaps %1 around a bit with a large trout_",
            'liebe': "https://www.youtube.com/watch?v=TfmJPDmaQdg",
        }

    def get_lang(self):
        return lang

    def conf(self):
        return Config.get(self)

    def get_raw_cmd(self, cmd_name):
        """Returns the raw cmd text or an empty string if command doesn't exists"""
        if cmd_name in self.conf():
            return "{} -> {}".format(cmd_name, self.conf()[cmd_name])
        return ""

    async def on_message(self, msg):
        """Will be called from on_message listener to react for custom cmds"""
        msg_args = self.cmd_re.findall(msg.content)
        cmd_name = msg_args[0][0][len(self.prefix):]
        cmd_args = msg_args[1:]
        if cmd_name not in self.conf():
            return
        elif (self.bot.ignoring.check_command_name(cmd_name, msg.channel)
                or self.bot.ignoring.check_user_command(msg.author, cmd_name)):
            raise commands.DisabledCommand()

        cmd_content = self.conf()[cmd_name]

        cmd_content = cmd_content.replace(wildcard_umention, msg.author.mention)
        cmd_content = cmd_content.replace(wildcard_user, utils.get_best_username(msg.author))

        all_args_positions = self.arg_list_re.findall(cmd_content)
        for i in range(0, len(all_args_positions)):
            if i >= len(cmd_args):
                break

            wildcard = all_args_positions[i][0]
            arg_num = int(all_args_positions[i][1]) - 1
            arg = cmd_args[arg_num][1] if cmd_args[arg_num][1] else cmd_args[arg_num][0]

            if all_args_positions[i][2]:
                for j in range(i + 1, len(cmd_args)):
                    arg_num = j
                    arg = "{} {}".format(arg, cmd_args[arg_num][1] if cmd_args[arg_num][1] else cmd_args[arg_num][0])

            try:
                member = await converter.convert_member(self.bot, msg, arg)
                if member is not None and self.bot.ignoring.check_user_command(member, cmd_name):
                    await msg.channel.send(Config.lang(self, 'user_blocked', utils.get_best_username(member)))
                    return
            except commands.CommandError:
                pass
            cmd_content = cmd_content.replace(wildcard, arg)

        await msg.channel.send(cmd_content)

    @commands.group(name="cmd", invoke_without_command=True, help="Adds, list or (for admins) removes a custom command",
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
            example = random.choice(list(self.conf().keys()))
            await ctx.send(Config.lang(self, 'current_prefix', self.conf()[prefix_key], example))
            return

        # set new prefix
        if not permChecks.check_full_access(ctx.author):
            await ctx.message.add_reaction(Config().CMDERROR)
            raise commands.BotMissingAnyRole(Config().FULL_ACCESS_ROLES)

        if new_prefix == ctx.prefix:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, 'invalid_prefix'))
        else:
            self.conf()[prefix_key] = new_prefix
            Config.save(self)
            await ctx.message.add_reaction(Config().CMDSUCCESS)

    @cmd.command(name="list", help="Lists all custom commands")
    async def cmd_list(self, ctx):
        cmds = []
        for k in self.conf().keys():
            if k != prefix_key:
                arg_list = self.arg_list_re.findall(self.conf()[k])
                cmds.append("{} <{}>".format(k, len(arg_list)))

        if not cmds:
            await ctx.send(Config.lang(self, 'list_no_cmds'))
            return

        cmds.sort(key=str.lower)
        cmd_msgs = utils.paginate(cmds, delimiter=", ")
        for msg in cmd_msgs:
            await ctx.send(msg)

    @cmd.command(name="raw", help="Gets the raw custom command text")
    async def cmd_raw(self, ctx, cmd_name):
        raw_text = self.get_raw_cmd(cmd_name)
        if raw_text:
            await ctx.send(self.conf()[prefix_key] + raw_text)
        else:
            await ctx.send(Config.lang(self, "raw_doesnt_exists", cmd_name))

    @cmd.command(name="add", help="Adds a custom command",
                 description="Adds a custom command. Following wildcards can be used, which will be replaced on "
                             "using:\n"
                             "%u: The user who uses the command\n"
                             "%um: Mentions the user who uses the command\n"
                             "%n: The nth command argument\n"
                             "%n*: The nth and all following arguments\n"
                             "Example: !cmd add test Argument1: %1 from user %u")
    async def cmd_add(self, ctx, cmd_name, *args):
        if not args:
            raise commands.MissingRequiredArgument(inspect.signature(self.cmd_add).parameters['args'])

        if cmd_name in self.conf():
            await ctx.send(Config.lang(self, "add_exists", cmd_name))
            await ctx.message.add_reaction(Config().CMDERROR)
        else:
            cmd_text = " ".join(args)
            self.conf()[cmd_name] = cmd_text
            Config.save(self)
            # await utils.log_to_admin_channel(ctx)
            await ctx.message.add_reaction(Config().CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Config.lang(self, 'cmd_added', self.get_raw_cmd(cmd_name)))

    @cmd.command(name="del", help="Deletes a custom command")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def cmd_del(self, ctx, cmd_name):
        if cmd_name in self.conf():
            cmd_raw = self.get_raw_cmd(cmd_name)
            del self.conf()[cmd_name]
            Config.save(self)
            # await utils.log_to_admin_channel(ctx)
            await ctx.message.add_reaction(Config().CMDSUCCESS)
            await utils.write_debug_channel(self.bot, Config.lang(self, 'cmd_removed', cmd_raw))
        else:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, "del_doesnt_exists", cmd_name))
