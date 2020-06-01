import discord
from discord.ext import commands

import botUtils
from config import config
from botUtils.blacklist import blacklist


class modCommands(commands.Cog, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        self.bot = bot
        self.blacklist = bot.blacklist

    @commands.group(name="blacklist", help="Manage the blacklist",
                    description="Add, removes or list users in the bot blacklist. "
                                "Users on the blacklist can't use any features of the bot. "
                                "Adding and removing users only permitted for mods.")
    async def blacklist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !blacklist <list|add|del>")

    @blacklist.command(name="list", help="Lists all users in the blacklist")
    async def blacklist_list(self, ctx):
        """Returns the current blacklist user list"""
        res = self.blacklist.get_blacklist_names()
        if not res:
            await ctx.send("Blacklist is empty.")
        else:
            await ctx.send(f"Users on Blacklist: {res}")

    @blacklist.command(name="add", help="Add an user to the blacklist", usage="<user>")
    @commands.has_any_role("mod", "botmaster")
    async def blacklist_add(self, ctx, user: discord.Member):
        """Adds the given user to the blacklist"""
        res = self.blacklist.add_user(user)
        if res:
            await ctx.send(f"User {user.nick} added to blacklist.")
        else:
            await ctx.send(f"User {user.nick} already on blacklist.")

    @blacklist.command(name="del", help="Remove an user from the blacklist", usage="<user>")
    @commands.has_any_role("mod", "botmaster")
    async def blacklist_del(self, ctx, user: discord.Member):
        """Removes the given user from blacklist"""
        res = self.blacklist.del_user(user)
        if res:
            await ctx.send(f"User {user.nick} removed from blacklist.")
        else:
            await ctx.send(f"User {user.nick} not on blacklist.")

    @commands.command(name="reload", help="Reloads the configuration.",
                      description="Reloads the configuration from config file. If errors occurs, check json file.")
    @commands.has_any_role("mod", "botmaster")
    async def reload_config(self, ctx):
        """Reloads the config file"""
        hasErrors = config.read_config_file()
        if hasErrors:
            sendMsg = "Error during reloading configuration."
        else:
            sendMsg = "Configuration reloaded."
        await ctx.send(sendMsg)
        await botUtils.write_debug_channel(self.bot, sendMsg)


def register(bot):
    bot.add_cog(modCommands(bot))
