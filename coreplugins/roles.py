import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from conf import Config
from botutils import utils

class RoleManagement():
    """
    Provides basic functions to create or add roles to users
    """

    async def add_user_role(member: discord.Member, role: discord.Role):
        """
        Adds a role to a server member
        :param member: the member
        :param role: the role to add
        :return: No exception in case of success
        """
        await member.add_roles(role)

    async def remove_user_role(member: discord.Member, role: discord.Role):
        """
        Removes a role from a server member
        :param member: the member
        :param role: the role to remove
        :return: No exception in case of success
        """
        await member.remove_roles(role)

    async def add_server_role(guild: discord.Guild, name, color: discord.Color = None, mentionable = True):
        """
        Creates a roll on the server
        :param guild: the server guild
        :param name: the role name
        :param color: the color for the role, if None Color.default()
        :param mentionable: if the role is mentionable
        :return: No exception in case of success
        """
        if color is None:
            color = discord.Color.default()
        await guild.create_role(name=name, color=color, mentionable=mentionable)

    async def remove_server_role(guild: discord.Guild, role: discord.Role):
        """
        Deletes a role on the server
        :param guild: the server guild
        :param role: the role to delete
        :return: No exception in case of success
        """
        old_id = role.id
        await role.delete()




class ReactionEventData():
    """
    Tuple for easier reaction event handling.
    """

    def __init__(self, user, channel, message, emoji, member = None):
        self.user = user
        self.channel = channel
        self.message = message
        self.emoji = emoji

        self.member = member

    async def convert(bot, payload: discord.RawReactionActionEvent):
        """
        Converts the raw payload data from on_raw_reaction_add and on_raw_reaction_remove
        to usable instances for easier event handling.
        :param bot: the bot instance to use to convert
        :param payload: the payload with raw event data
        :return: the converted ReactionEvent instance
        """
        channel = bot.get_channel(payload.channel_id)
        user = bot.get_user(payload.user_id)
        member = None
        try:
            member = self.bot.guild.get_member(payload.user_id)
        except:
            pass
        message = await channel.fetch_message(payload.message_id)

        return ReactionEventData(user, channel, message, payload.emoji, member)


class Plugin(BasePlugin, name="Role Management"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        
        @bot.listen()
        async def on_raw_reaction_add(payload):
            pass

        @bot.listen()
        async def on_raw_reaction_remove(payload):
            pass


        #@bot.listen()
        #async def on_raw_reaction_add(payload):
        #    channel = self.bot.get_channel(payload.channel_id)
        #    user = self.bot.guild.get_member(payload.user_id)
        #    message = await channel.fetch_message(payload.message_id)
        #    emoji = payload.emoji

        #    msg = f"{channel.name}, {utils.get_best_username(user)}, {emoji} added\n{message.content}"

        #    await utils.write_debug_channel(self.bot, msg)

        #    new_emoji = discord.utils.get(bot.emojis, name='mud')
        #    await message.add_reaction(new_emoji)

        #@bot.listen()
        #async def on_raw_reaction_remove(payload):
        #    channel = self.bot.get_channel(payload.channel_id)
        #    user = self.bot.guild.get_member(payload.user_id)
        #    message = await channel.fetch_message(payload.message_id)
        #    emoji = payload.emoji

        #    msg = f"{channel.name}, {utils.get_best_username(user)}, {emoji} removed\n{message.content}"

        #    await utils.write_debug_channel(self.bot, msg)
            
        #    new_emoji = discord.utils.get(bot.emojis, name='kip')
        #    await message.add_reaction(new_emoji)

    def conf(self):
        return Config().get(self)


    @commands.group(name="role", invoke_without_command=True)
    async def role(self, ctx, user: discord.Member, action, role: discord.Role):
        # todo: perm check: Only usable for users with corresponding master role. Mods can use that for all roles.

        if action.lower() == "add":
            if role in user.roles:
                await ctx.send("User {} has role {} already.".format(utils.get_best_username(user), role))
                return
            await RoleManagement.add_user_role(user, role)
            await ctx.send("I can't check it, but role {} should be added to {}.".format(role, utils.get_best_username(user)))
        elif action.lower() == "del":
            if role not in user.roles:
                await ctx.send("User {} doesn't have role {}.".format(utils.get_best_username(user), role))
                return
            await RoleManagement.remove_user_role(user, role)
            await ctx.send("I can't check it, but role {} should be removed from {}.".format(role, utils.get_best_username(user)))
        else:
            raise commands.BadArgument("Only add or del possible as second argument.")

        await utils.log_to_admin_channel(ctx)

    @role.command(name="add")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_add(self, ctx, role_name, emoji_or_masterrole = None, color: discord.Color = None):
        existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
        if existing_role is not None:
            await ctx.send("A role with name {} already exists.".format(role_name))
            return

        emoji = None
        masterrole = None
        try:
            emoji = await commands.EmojiConverter().convert(ctx, emoji_or_masterrole)
        except:
            pass
        try:
            masterrole = await commands.RoleConverter().convert(ctx, emoji_or_masterrole)
        except:
            pass

        if emoji is None and masterrole is None:
            try:
                color = await commands.ColourConverter().convert(ctx, emoji_or_masterrole)
            except:
                color = discord.Color.default()

        await RoleManagement.add_server_role(ctx.guild, role_name, color)
        await ctx.send("I can't check it, but the role {} should be created with color {} now.".format(role_name, color))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="del")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_del(self, ctx, role: discord.Role):
        await RoleManagement.remove_server_role(ctx.guild, role)
        await ctx.send("I can't check it, but the role {} should be deleted now.".format(role.name))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="request")
    async def role_request(self, ctx, role: discord.Role):
        pass

    @role.command(name="update")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_update(self, ctx):
        await utils.log_to_admin_channel(ctx)
        pass
