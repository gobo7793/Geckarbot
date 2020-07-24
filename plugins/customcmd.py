import inspect
from discord.ext import commands

import Geckarbot
from conf import Config
from botutils import utils


lang = {
    'en': {
        'raw_doesnt_exists': "A command \"{}\" doesn't exists, but you can create it!",
        'del_doesnt_exists': "Command \"{}\" can't be deleted, because it doesn't exists...",
        'add_exists': "A command \"{}\" already exists.",
        'list_no_cmds': "I don't know any custom commands :frowning:",
        'cmd_added': "Added custom command: {}",
        'cmd_removed': "Added custom command: {}",
    },
    'de': {
        'raw_doesnt_exists': "Ein Kommando \"{}\" existiert nicht, erstell es doch einfach selbst!",
        'del_doesnt_exists': "Das Kommando \"{}\" kann nicht gelöscht werden weil es nicht existiert...",
        'add_exists': "Ein Kommando \"{}\" existiert bereits.",
        'list_no_cmds': "Ich kenne keine Kommandos :frowning:",
        'cmd_added': "Kommando hinzugefügt: {}",
        'cmd_removed': "Kommando gelöscht: {}",
    }
}


prefix_key = "_prefix"
wildcard_user = "%u"
wildcard_pref = "%"


class Plugin(Geckarbot.BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.prefix = self.conf()[prefix_key]

        @bot.listen()
        async def on_message(msg):
            if (msg.content.startswith(self.prefix) and
                    msg.author.id != self.bot.user.id):
                await self.on_message(msg)

    def default_config(self):
        return {
            prefix_key: '+'
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
        msg_args = msg.content.split(' ')
        cmd_name = msg_args[0][len(self.prefix):]
        cmd_args = msg_args[1:]
        if cmd_name not in self.conf():
            return

        cmd_content = self.conf()[cmd_name]

        cmd_content = cmd_content.replace(wildcard_user, utils.get_best_username(msg.author))
        for i in range(0, len(cmd_args)):
            arg = cmd_args[i]
            wildcard = wildcard_pref + str(i + 1)
            cmd_content = cmd_content.replace(wildcard, arg)

        await msg.channel.send(cmd_content)

    @commands.group(name="cmd", invoke_without_command=True, help="Adds, list or (for admins) removes a custom command",
                    description="Adds, list or removes a custom command. Custom commands can be added and removed in "
                                "runtime. To use a custom command, the message must start with the setted prefix.")
    async def cmd(self, ctx):
        await ctx.send_help(self.cmd)

    @cmd.command(name="prefix", help="Sets the custom command prefix")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def cmd_prefix(self, ctx, prefix):
        self.conf()[prefix_key] = prefix
        Config.save(self)
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    @cmd.command(name="list", help="Lists all custom commands")
    async def cmd_list(self, ctx):
        cmds = []
        for k in self.conf().keys():
            if k != prefix_key:
                cmds.append(k)

        if not cmds:
            await ctx.send(Config.lang(self, 'list_no_cmds'))
            return

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

    @cmd.command(name="add", help="Adds a custom command")
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
            await utils.log_to_admin_channel(ctx)
            await utils.write_debug_channel(self.bot, Config.lang(self, 'cmd_added', self.get_raw_cmd(cmd_name)))
            await ctx.message.add_reaction(Config().CMDSUCCESS)

    @cmd.command(name="del", help="Deletes a custom command")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def cmd_del(self, ctx, cmd_name):
        if cmd_name in self.conf():
            cmd_raw = self.get_raw_cmd(cmd_name)
            del self.conf()[cmd_name]
            Config.save(self)
            await utils.log_to_admin_channel(ctx)
            await utils.write_debug_channel(self.bot, Config.lang(self, 'cmd_removed', cmd_raw))
            await ctx.message.add_reaction(Config().CMDSUCCESS)
        else:
            await ctx.send(Config.lang(self, "del_doesnt_exists", cmd_name))
            await ctx.message.add_reaction(Config().CMDERROR)
