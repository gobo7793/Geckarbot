import discord
from discord.ext import commands

from conf import Config
from botUtils import utils, permChecks, enums


class Plugin(commands.Cog, name="Bot Management Commands"):
    """Commands for moderation"""

    def __init__(self, bot):
        self.bot = bot
        super(commands.Cog).__init__()
        bot.register(self)
        self.blacklist = Blacklist(bot)
        self.greylist = Greylist(bot)
        bot.coredata['blacklist'] = self.blacklist
        bot.coredata['greylist'] = self.greylist

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

    @commands.command(name="version", help="Returns the running bot version.")
    async def return_version(self, ctx):
        """Returns the version"""
        await ctx.send(f"Running Geckarbot v{Config().VERSION}")

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
            await ctx.send(f"User {user.name} added to blacklist.")
        else:
            await ctx.send(f"User {user.name} already on blacklist.")

    @blacklist.command(name="del", help="Remove an user from the blacklist", usage="<user>")
    @commands.has_any_role("mod", "botmaster")
    async def blacklist_del(self, ctx, user: discord.Member):
        """Removes the given user from blacklist"""
        res = self.blacklist.del_user(user)
        if res:
            await ctx.send(f"User {user.name} removed from blacklist.")
        else:
            await ctx.send(f"User {user.name} not on blacklist.")
            

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


class Blacklist(object):
    """Manage the user banlist for using the bot"""
    
    def __init__(self, bot):
        self.bot = bot

    def add_user(self, user: discord.Member):
        """Adds user to bot blacklist, returns True if added"""
        if not self.is_member_on_blacklist(user):
            Config().blacklist.append(user.id)
            Config().write_config_file()
            return True
        else:
            return False

    def del_user(self, user:discord.Member):
        """Deletes user to bot blacklist, returns True if deleted"""
        if self.is_member_on_blacklist(user):
            Config().blacklist.remove(user.id)
            Config().write_config_file()
            return True
        else:
            return False

    def get_blacklist_names(self):
        """Returns the blacklisted member names"""
        blacklisted_members = ", ".join([self.bot.get_user(id).name for id in Config().blacklist])
        return blacklisted_members

    def is_member_on_blacklist(self, user: discord.Member):
        """Returns if user is on bot blacklist"""
        return self.is_userid_on_blacklist(user.id)

    def is_userid_on_blacklist(self, userID: int):
        """Returns if user id is on bot blacklist"""
        if userID in Config().blacklist:
            return True
        else:
            return False


class Greylist(object):
    """Manage the user greylist for using the bot.
    Users on greylist can't play the bot provided games on their greylist.
    """
    
    def __init__(self, bot):
        self.bot = bot

    def add(self, user: discord.Member, game: enums.GreylistGames = None):
        """Adds the given game to users greylist.
        If game is None, all games will be added.
        If user is already on list, the user game list will be updated.
        If user is new on list, True will be returned, otherwise False.
        """
        if game is None:
            game = enums.GreylistGames.ALL
        was_added = True
        if self.is_user_on_greylist(user, game):
            game = Config().greylist[user.id] | game
            was_added = False
        Config().greylist[user.id] = game
        Config().write_config_file()
        return was_added

    def remove(self, user:discord.Member, game: enums.GreylistGames = None):
        """Removes the given game from users greylist.
        If game is None, all games will be removed.
        If user is not on list, None will be returned.
        If user was completely removed, True will be returned, otherwise False.
        """
        if game is None:
            game = enums.GreylistGames.ALL
        was_removed = None
        if self.is_user_on_greylist(user, game):
            Config().greylist[user.id] = Config().greylist[user.id] & ~game
            was_removed = False
            if Config().greylist[user.id] is enums.GreylistGames.No_Game:
                del(Config().greylist[user.id])
                was_removed = True
        Config().write_config_file()
        return was_removed

    def get_greylist_names(self):
        """Returns the greylisted members"""
        greylisted_members = ", ".join([self.bot.get_user(id).name for id in Config().greylist])
        return greylisted_members

    def is_user_on_greylist(self, user:discord.Member, game: enums.GreylistGames):
        """Returns if user is for the given game on the greylist"""
        return self.is_userid_on_greylist(user.id, game)

    def is_userid_on_greylist(self, userID: int, game: enums.GreylistGames):
        """Returns if user id is for the given game on the greylist"""
        if userID in Config().greylist:
            if Config().greylist[userID] & game is not 0:
                return True
        return False
