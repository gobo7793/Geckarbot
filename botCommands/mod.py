import discord
from discord.ext import commands

from botUtils.blacklist import blacklist

class modCommands(commands.Cog, name="Moderation Commands"):
    """Commands for moderation"""

    def __init__(self, bot, blacklist):
        self.bot = bot
        self.blacklist = blacklist

    @commands.group(name="blacklist", help="Manage the blacklist",
                    description="Add, removes or list users in the bot blacklist. Users on the blacklist can't use any features of the bot. Adding and removing users only permitted for mods.")
    async def blacklist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !blacklist <list|add|del>")

    @blacklist.command(name="list", help="Lists all users in the blacklist")
    async def blacklist_list(self, ctx):
        """Returns the current blacklist user list"""
        res = self.blacklist.getBlacklist()
        if not res:
            await ctx.send("Blacklist is empty.")
        else:
            await ctx.send(f"Users on Blacklist: {res}")

    @blacklist.command(name="add", help="Add an user to the blacklist", usage="<user>")
    @commands.has_any_role("mod", "botmaster")
    async def blacklist_add(self, ctx, user:discord.Member):
        """Adds the given user to the blacklist"""
        res = self.blacklist.addUserToBlacklist(user)
        if res:
            await ctx.send(f"User {user.name} added to blacklist.")
        else:
            await ctx.send(f"User {user.name} already on blacklist.")

    @blacklist.command(name="del", help="Remove an user from the blacklist", usage="<user>")
    @commands.has_any_role("mod", "botmaster")
    async def blacklist_del(self, ctx, user:discord.Member):
        """Removes the given user from blacklist"""
        res = self.blacklist.delUserFromBlacklist(user)
        if res:
            await ctx.send(f"User {user.name} removed from blacklist.")
        else:
            await ctx.send(f"User {user.name} not on blacklist.")
