from copy import deepcopy

import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from conf import Config
from botutils import utils, permChecks

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
            member = bot.guild.get_member(payload.user_id)
        except:
            pass
        message = await channel.fetch_message(payload.message_id)

        return ReactionEventData(user, channel, message, payload.emoji, member)


class Plugin(BasePlugin, name="Role Management"):
    """
    Role Management Plugin.
    Config format for roles:
    key: role_id, value: ([0]: emoji str representation, [1]: master_role_id)
    """

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        
        @bot.listen()
        async def on_raw_reaction_add(payload):
            await self.update_reaction_based_user_role(payload, True)

        @bot.listen()
        async def on_raw_reaction_remove(payload):
            await self.update_reaction_based_user_role(payload, False)


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

    async def create_message_text(self, server_roles, ctx):
        """
        Returns the message text for the role manage init message
        including the reactions and master roles for the roles
        :param server_roles: the roles on the server
        :param ctx: The context of the used command to create the new message
        """
        msg = "{}\n".format(Config().get(self)['message']['content'])
        
        for rid in self.rc():
            role = discord.utils.get(server_roles, id=rid)
            emote_msg = ""
            masterrole_msg = ""

            if self.rc()[rid][0]:
                emote_msg = "Reaction: {}".format(await utils.emojize(self.rc()[rid][0], ctx))
            if self.rc()[rid][1] != 0:
                masterrole = discord.utils.get(server_roles, id=self.rc()[rid][1])
                masterrole_msg = "Masterrole: {}".format(masterrole.name)

            todo_part = ""
            if emote_msg and masterrole_msg:
                todo_part = "{}, {}".format(emote_msg, masterrole_msg)
            elif emote_msg:
                todo_part = emote_msg
            elif masterrole_msg:
                todo_part = masterrole_msg
            else:
                todo_part = "Only via Admins."

            msg += "\n{} - {}".format(role.name, todo_part)

        return msg

    async def update_role_management(self, ctx):
        """
        Updates saved roles from server,
        removes not existing roles from config,
        remove not existing roles from init message and
        add new roles and their emojis and reactions to the init message.
        """

        # Remove old roles
        current_server_roles = await self.bot.guild.fetch_roles()
        server_role_ids = [r.id for r in current_server_roles]
        copy_roles = self.rc()
        removed_roles = deepcopy(copy_roles)
        for role_in_config in self.rc():
            if role_in_config in server_role_ids:
                del(removed_roles[role_in_config])

        for role_to_remove in removed_roles:
            del(self.rc()[role_to_remove])
        roles_debug = self.rc()

        # update message
        message_text = await self.create_message_text(current_server_roles, ctx)

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
                emoji_id = removed_roles[removed_role][0]
                if not emoji_id:
                    continue
                emote = await utils.emojize(emoji_id, ctx)
                await message.clear_reaction(emote)

        # add reactions for new roles
        for role_config in self.rc():
            emoji_id = self.rc()[role_config][0]
            if not emoji_id:
                continue
            emote = await utils.emojize(emoji_id, ctx)
            await message.add_reaction(emote)

        Config().save(self)

    async def update_reaction_based_user_role(self, payload, role_add = None):
        """
        Updates the user roles based on the reaction events.
        :param payload: The RawReactionActionEvent data
        :param role_add: For role adding set True, for role removing False.
                         If None, this function does nothing.
        """
        if (payload.channel_id != Config().get(self)['message']['channel_id']
            or payload.message_id != Config().get(self)['message']['message_id']
            or role_add is None):
            return

        data = await ReactionEventData.convert(self.bot, payload)
        emoji_str = str(data.emoji)
        update_type = ""
        has_role_update = False
        for configured_role in self.rc():
            configured_emoji = self.rc()[configured_role][0]
            if configured_emoji == emoji_str:
                role = discord.utils.get(self.bot.guild.roles, id=configured_role)
                if role_add and role not in data.member.roles:
                    update_type = "add"
                    await RoleManagement.add_user_role(data.member, role)
                    has_role_update = True
                elif not role_add and role in data.member.roles:
                    admin_type = "remove"
                    await RoleManagement.remove_user_role(data.member, role)
                    has_role_update = True

        if has_role_update:
            await utils.log_to_admin_channel_without_ctx(self.bot,
                    **{'Type': "Self-assign role",
                        'Action': update_type,
                        'User': data.member.mention,
                        'Reaction': data.emoji,
                        'role': role})

    @commands.group(name="role", invoke_without_command=True)
    async def role(self, ctx, user: discord.Member, action, role: discord.Role):
        # perm check: Only usable for users with corresponding master role. Mods can use that for all roles.
        if not permChecks.check_full_access(ctx.author):
            if role.id not in self.rc():
                raise commands.CheckFailure(message="You can't add or remove roles via bot command.")

            need_master_role_id = self.rc()[role.id][1]
            if need_master_role_id is None or need_master_role_id == 0:
                raise commands.CheckFailure(message="The role {} has no master role, so I won't let you do this.".format(role.name))

            if need_master_role_id not in [r.id for r in ctx.author.roles]:
                raise commands.MissingRole(need_master_role_id)

        if action.lower() == "add":
            if role in user.roles:
                await ctx.send("User {} has role {} already.".format(utils.get_best_username(user), role))
                return
            await RoleManagement.add_user_role(user, role)
            await ctx.send("My trainer was to lazy to let me check it, but role {} should be added to {}.".format(role, utils.get_best_username(user)))
        elif action.lower() == "del":
            if role not in user.roles:
                await ctx.send("User {} doesn't have role {}.".format(utils.get_best_username(user), role))
                return
            await RoleManagement.remove_user_role(user, role)
            await ctx.send("My trainer was to lazy to let me check it, but role {} should be removed from {}.".format(role, utils.get_best_username(user)))
        else:
            raise commands.BadArgument("I don't know that move, I only know add or del for argument action.")

        await utils.log_to_admin_channel(ctx)

    @role.command(name="add")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_add(self, ctx, role_name, emoji_or_masterrole, color: discord.Color = None):
        emoji_str = await utils.demojize(emoji_or_masterrole, ctx)
        try:
            masterrole = await commands.RoleConverter().convert(ctx, emoji_or_masterrole)
            masterrole_id = masterrole.id
            emoji_str = ""
        except:
            masterrole_id = 0

        if not emoji_str and masterrole_id == 0:
            try:
                color = await commands.ColourConverter().convert(ctx, emoji_or_masterrole)
            except:
                color = discord.Color.default()

        existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
        if existing_role is not None:
            if existing_role.id in self.rc():
                # Update role data
                if not emoji_str:
                    emoji_str = self.rc()[existing_role.id][0]
                if masterrole_id == 0:
                    masterrole_id = self.rc()[existing_role.id][1]
                self.rc()[existing_role.id] = (emoji_str, masterrole_id)
                await self.update_role_management(ctx)
                await ctx.send("I was to lazy to create a new role with the name {}, so I updated the existing.".format(role_name))
            else:
                # role exists on server, but not in config, add it there
                self.rc()[existing_role.id] = (emoji_str, masterrole_id)
                await self.update_role_management(ctx)
                await ctx.send("I was to lazy to create a new role with the name {} on the server, so I just added it to my own role list.".format(role_name))
            return

        # Execute role add
        new_role = await RoleManagement.add_server_role(ctx.guild, role_name, color)
        self.rc()[new_role.id] = (emoji_str, masterrole_id)
        await self.update_role_management(ctx)
        await ctx.send("My trainer was to lazy to let me check it, but the role {} should be created with color {} now.".format(role_name, color))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="del")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_del(self, ctx, role: discord.Role):
        await RoleManagement.remove_server_role(ctx.guild, role)
        await self.update_role_management(ctx)
        await ctx.send("My trainer was to lazy to let me check it, but the role {} should be deleted now.".format(role.name))
        await utils.log_to_admin_channel(ctx)

    @role.command(name="request")
    async def role_request(self, ctx, role: discord.Role):
        # todo
        pass

    @role.command(name="update")
    #@commands.has_any_role(*Config().FULL_ACCESS_ROLES)
    async def role_update(self, ctx, *message_content):
        if len(message_content) > 0:
            Config().get(self)['message']['content'] = " ".join(message_content)
        Config().save(self)
        await self.update_role_management(ctx)
        await ctx.send("I'm a lazy Treecko, but especially for you, I updated my role management.")
        await utils.log_to_admin_channel(ctx)
