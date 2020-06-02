import discord
from discord.ext import commands

from conf import Config
from botUtils import utils, permChecks, enums
from botUtils.blacklist import Blacklist
from botUtils.greylist import Greylist


class modCommands(commands.Cog, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        self.bot = bot
        self.blacklist = bot.blacklist
        self.greylist = bot.greylist

######
# Misc commands
######

    @commands.command(name="reload", help="Reloads the configuration.",
                      description="Reloads the configuration from config file. If errors occurs, check json file.")
    @commands.has_any_role("mod", "botmaster")
    async def reload_config(self, ctx):
        """Reloads the config file"""
        hasErrors = Config().read_config_file()
        if hasErrors:
            sendMsg = "Error during reloading configuration."
        else:
            sendMsg = "Configuration reloaded."
        await ctx.send(sendMsg)
        await utils.write_debug_channel(self.bot, sendMsg)

######
# Blacklist
######

    @commands.group(name="blacklist", help="Manage the blacklist",
                    usage="<list|add|del>",
                    description="Add, removes or list users on the bot blacklist. "
                                "Users on the blacklist can't use any features of the bot. "
                                "Adding and removing users only permitted for mods.")
    async def blacklist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !blacklist <list|add|del>")

    @blacklist.command(name="list", help="Lists all users on the blacklist")
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
            

######
# Greylist
######

    @commands.group(name="greylist", help="Manage the greylist",
                    usage="<list|add|del>",
                    description="Add, removes or list users and their games on the greylist. "
                                "Users on the greylist can't play the listed bot games. "
                                "Users can add and remove games for theirselfes, "
                                "but for other users only by mods.")
    async def greylist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: !greylist <list|add|del>")

    @greylist.command(name="list", help="Lists all users on the greylist")
    async def greylist_list(self, ctx):
        """Returns the current blacklist user list"""
        userlist = ""
        for userid in Config().greylist:
            username = self.bot.get_user(userid).name
            games = str(enums.GreylistGames(Config().greylist[userid]))

            # convert game names here
            list_begin = games.find(".")
            game_list = games[list_begin + 1:].replace("|", ", ").replace("_", " ")
            userlist += f"- {username}: {game_list}\n"

        if not userlist:
            await ctx.send("Greylist is empty.")
        else:
            userlist = userlist[:-1]
            await ctx.send(f"**Users on Greylist:**\n{userlist}")

    @greylist.command(name="add", help="Add a bot game to greylist.", usage="[user] [game]",
                      description="Adds a bot game to the greylist. " 
                                  "Users can only add a game to their own greylist, "
                                  "but mods also for other users. "
                                  "If no game is given, all games will be added.")
    async def greylist_add(self, ctx, user_game = None, game = None):
        """Adds a bot game to the greylist.
        Users can only add a game to their own greylist,
        but mods also for other users.
        If no game is given, all games will be added."""

        user = ctx.author
        converter = commands.UserConverter()
        member = None
        try:
            # Note: If member is bot itself, ClientUser type will returned
            member = await converter.convert(ctx, user_game)
        except:
            pass
        if isinstance(member, discord.User):
            user = member
            if member is ctx.author:
                member = None
        else:
            game = user_game

        is_mod = permChecks.check_full_access(ctx.author)
        if isinstance(member, discord.User) and not is_mod:
            raise commands.MissingAnyRole(["mod", "botmaster"])

        game_enum = getattr(enums.GreylistGames, str(game), enums.GreylistGames.ALL)
        res = self.greylist.add(user, game_enum)
        if res is True:
            await ctx.send("User added on greylist.")
        else:
            await ctx.send("User's greylist updated.")

    @greylist.command(name="del", help="Remove a bot game from greylist.", usage="[user] [game]",
                      description="Removes a bot game to the greylist. " 
                                  "Users can only removes a game to their own greylist, "
                                  "but mods also for other users. "
                                  "If no game is given, all games will be removed.")
    async def greylist_del(self, ctx, user_game = None, game = None):
        """"Removes a bot game to the greylist.
        Users can only removes a game to their own greylist,
        but mods also for other users.
        If no game is given, all games will be removed."""

        user = ctx.author
        converter = commands.UserConverter()
        member = None
        try:
            # Note: If member is bot itself, ClientUser type will returned
            member = await converter.convert(ctx, user_game)
        except:
            pass
        if isinstance(member, discord.User):
            user = member
            if member is ctx.author:
                member = None
        else:
            game = user_game

        is_mod = permChecks.check_full_access(ctx.author)
        if isinstance(member, discord.User) and not is_mod:
            raise commands.MissingAnyRole(["mod", "botmaster"])
            
        game_enum = getattr(enums.GreylistGames, str(game), enums.GreylistGames.ALL)
        res = self.greylist.remove(user, game_enum)
        if res is None:
            await ctx.send("User not on greylist.")
        elif res is True:
            await ctx.send("User removed from greylist.")
        else:
              await ctx.send("User's greylist updated.")

def register(bot):
    bot.add_cog(modCommands(bot))
