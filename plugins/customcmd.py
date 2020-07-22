import discord
from discord.ext import commands

import Geckarbot
from conf import Config


lang = {
    'en': {

    },
    'de': {

    }
}


class Plugin(Geckarbot.BasePlugin, name="Custom CMDs"):
    """Provides custom cmds"""

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True
        bot.register(self)

        self.prefix = Config.get(self)['_prefix']

        @bot.listen()
        async def on_message(msg):
            if (msg.content.startswith(self.prefix) and
                    msg.author.id != self.bot.user.id):
                await self.on_message(msg)

    def default_config(self):
        return {
            '_prefix': '+'
        }

    def get_lang(self):
        return lang

    async def on_message(self, msg):
        """Will be called from on_message listener to react for custom cmds"""
        cmd_name = msg.content.split(' ', 1)[0][len(self.prefix):]
        if cmd_name not in Config.get(self):
            return

        cmd_content = Config.get(self)[cmd_name]
        await msg.channel.send(cmd_content)

    @commands.group(name="cmd", invoke_without_command=True, help="Adds, list or (for admins) removes a custom command",
                    description="Adds, list or removes a custom command. Custom commands can be added and removed in "
                                "runtime. To use a custom command, the message must start with the setted prefix.")
    async def cmd(self, ctx):
        await ctx.send_help(self.cmd)

    @cmd.command(name="prefix", help="Sets the custom command prefix")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def cmd_prefix(self, ctx, prefix):
        Config.get(self)['_prefix'] = prefix
        Config.save(self)
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    @cmd.command(name="list", help="Lists all custom commands")
    async def cmd_list(self, ctx):
        pass

    @cmd.command(name="raw", help="Gets the raw custom command text")
    async def cmd_raw(self, ctx):
        pass

    @cmd.command(name="add", help="Adds a custom command")
    async def cmd_add(self, ctx, cmd_name, *args):
        pass

    @cmd.command(name="del", help="Deletes a custom command")
    @commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def cmd_del(self, ctx, cmd_name):
        pass
