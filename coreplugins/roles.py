from copy import deepcopy

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
        :return: The created role
        """
        if color is None:
            color = discord.Color.default()
        return await guild.create_role(name=name, color=color, mentionable=mentionable)

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
    """
    Role Management Plugin.
    Config format for roles:
    key: role_id, value: ([0]: emoji, [1]: master_role)
    """

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

    def default_config(self):
        return {
            'message': {
                'channel_id': Config().CHAN_IDS['announcements'],
                'message_id': 0,
                'content': ""
                },
            'roles': {}
            }

    def rc(self):
        """Returns the roles config"""
        return Config().get(self)['roles']

    def create_message_text(self):
        """Returns the message text for the role manage init message"""
        return "TEEEEEST"

    async def update_role_management(self, ctx):
        """
        Updates saved roles from server,
        removes not existing roles from config,
        remove not existing roles from init message and
        add new roles and their emojis and reactions to the init message.
        """

        # Remove old roles
        current_server_roles = await self.bot.guild.fetch_roles()
        roles_to_remove = list(set(self.rc()) - set(r.id for r in current_server_roles))
        removed_roles = deepcopy(roles_to_remove)
        Config().get(self)['roles'] = list(set(self.rc()) - set(roles_to_remove)) # hier löscht der das dict in eine liste mit den IDs

        # update message
        message_text = self.create_message_text()

        channel = self.bot.get_channel(Config().get(self)['message']['channel_id'])
        try:
            message = await channel.fetch_message(Config().get(self)['message']['message_id'])
        except:
            message = None

        if message is None:
            await utils.write_debug_channel(self.bot, "Creating new role management init message.")
            message = await channel.send(message_text)
            Config().get(self)['message']['message_id'] = message.id
        else:
            await message.edit(content=message_text)

        # remove reactions from old roles
        for removed_role in removed_roles:
            if removed_roles[removed_role][0] is not None:
                await message.clear_reaction(removed_roles[removed_role][0])

        # add reactions for new roles
        for role_config in self.rc():
            roles_debug = self.rc()
            if self.rc()[role_config][0] is None or self.rc()[role_config][0] == 0:
                continue
            emoji = await commands.EmojiConverter().convert(ctx, role_config[0])
            await message.add_reaction(emoji)

        Config().save(self)

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
        try:
            emoji = await commands.EmojiConverter().convert(ctx, emoji_or_masterrole)
            emoji_id = emoji.id
        except:
            emoji = None
            emoji_id = 0
        try:
            masterrole = await commands.RoleConverter().convert(ctx, emoji_or_masterrole)
        except:
            masterrole = None

        if emoji is None and masterrole is None:
            try:
                color = await commands.ColourConverter().convert(ctx, emoji_or_masterrole)
            except:
                color = discord.Color.default()

        existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
        if existing_role is not None:
            if existing_role.id in self.rc():
                # Full existing role handling
                await ctx.send("A role with name {} already exists.".format(role_name))
            else:
                # role exists on server, but not in config, add it there
                self.rc()[existing_role.id] = (emoji_id, masterrole)
                await ctx.send("Role {} added to config.".format(role_name))
                await self.update_role_management(ctx)
            return

        # Execute role add
        new_role = await RoleManagement.add_server_role(ctx.guild, role_name, color)
        self.rc()[new_role.id] = (emoji_id, masterrole)
        await self.update_role_management(ctx)
        await ctx.send("I can't check it, but the role {} should be created with color {} now.".format(role_name, color))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="del")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_del(self, ctx, role: discord.Role):
        await RoleManagement.remove_server_role(ctx.guild, role)
        await self.update_role_management(ctx)
        await ctx.send("I can't check it, but the role {} should be deleted now.".format(role.name))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="request")
    async def role_request(self, ctx, role: discord.Role):
        # todo
        pass

    @role.command(name="update")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_update(self, ctx, *message_content):
        Config().get(self)['message']['content'] = message_content
        Config().save(self)
        await self.update_role_management(ctx)
        await ctx.send("Role management and message updated.")
        await utils.log_to_admin_channel(ctx)
