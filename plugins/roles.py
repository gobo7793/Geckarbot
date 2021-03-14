import asyncio
from copy import deepcopy

import discord
import emoji
from discord.ext import commands

from base import BasePlugin, NotFound
from botutils import utils, permchecks, converters, stringutils
from botutils.utils import add_reaction
from data import Storage, Config, Lang
from subsystems import reactions, help


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


async def add_server_role(guild: discord.Guild, name, color: discord.Color = None, mentionable=True):
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


async def remove_server_role(role: discord.Role):
    """
    Deletes a role on the server
    :param role: the role to delete
    :return: No exception in case of success
    """
    await role.delete()


class Plugin(BasePlugin, name="Role Management"):
    """
    Role Management Plugin.
    Config format for roles:
    key: role_id, value: {emoji: emoji str representation, modrole: mod_role_id}
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.can_reload = True

        bot.register(self, help.DefaultCategories.MOD)
        for cmd in self.get_commands():
            if cmd.name == "role msg":
                self.bot.helpsys.default_category(help.DefaultCategories.MISC).add_command(cmd)

        async def get_init_msg_data():
            if self.has_init_msg_set:
                bot.reaction_listener.register(await self.get_init_msg(), self.update_reaction_based_user_role)

        asyncio.run_coroutine_threadsafe(get_init_msg_data(), self.bot.loop)
        # asyncio.get_event_loop().create_task(get_init_msg_data())

    def default_storage(self):
        return {
            'message': {
                'channel_id': 0,
                'message_id': 0,
                'content': ""
            },
            'roles': {}
        }

    def command_help_string(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_{}".format(command.name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_description(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_desc_{}".format(command.name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_usage(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_usage_{}".format(command.name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def rc(self):
        """Returns the roles config"""
        return Storage.get(self)['roles']

    @property
    def has_init_msg_set(self):
        return (Storage.get(self)['message']['channel_id'] != 0
                and Storage.get(self)['message']['message_id'] != 0)

    async def get_init_msg(self):
        """Returns the role management init message or None if not set"""
        if self.has_init_msg_set:
            channel = self.bot.get_channel(Storage.get(self)['message']['channel_id'])
            return await channel.fetch_message(Storage.get(self)['message']['message_id'])
        else:
            return None

    async def create_message_text(self, server_roles, ctx):
        """
        Returns the message text for the role manage init message
        including the reactions and mod roles for the roles
        :param server_roles: the roles on the server
        :param ctx: The context of the used command to create the new message
        """
        msg = "{}\n".format(Storage.get(self)['message']['content'])

        for rid in self.rc():
            role = discord.utils.get(server_roles, id=rid)
            emote_msg = ""
            modrole_msg = ""

            if self.rc()[rid]['emoji']:
                emote_msg = Lang.lang(self, 'init_reaction', await stringutils.emojize(self.rc()[rid]['emoji'], ctx))
            if self.rc()[rid]['modrole'] != 0:
                modrole = discord.utils.get(server_roles, id=self.rc()[rid]['modrole'])
                modrole_msg = Lang.lang(self, 'init_modrole', modrole.name)

            if emote_msg and modrole_msg:
                msg += "\n{} - {}; {}".format(emote_msg, role.name, modrole_msg)
            elif emote_msg:
                msg += "\n{} - {}".format(emote_msg, role.name)
            elif modrole_msg:
                msg += "\n{}; {}".format(role.name, modrole_msg)
            else:
                msg += "\n{}; {}".format(role.name, Lang.lang(self, 'init_admin'))

        return msg

    async def update_role_management(self, ctx):
        """
        Updates saved roles from server,
        removes not existing roles from config,
        remove not existing roles from init message and
        add new roles and their emojis and reactions to the init message.
        """

        channel = self.bot.get_channel(Storage.get(self)['message']['channel_id'])
        if channel is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await utils.write_mod_channel(Lang.lang(self, 'must_set_channel_id'))
            await ctx.send(Lang.lang(self, 'must_set_channel_id'))
            return

        # Remove old roles
        current_server_roles = await self.bot.guild.fetch_roles()
        server_role_ids = [r.id for r in current_server_roles]
        removed_roles = deepcopy(self.rc())
        for role_in_config in self.rc():
            if role_in_config in server_role_ids:
                del (removed_roles[role_in_config])
                # remove emojis and mod roles that aren't on server anymore
                if self.rc()[role_in_config]['modrole'] not in server_role_ids:
                    self.rc()[role_in_config]['modrole'] = 0
                if (self.rc()[role_in_config]['emoji']
                        and emoji.emoji_count(emoji.emojize(self.rc()[role_in_config]['emoji'], True)) < 1):
                    for e in self.bot.emojis:
                        if str(e) == self.rc()[role_in_config]['emoji']:
                            break
                    else:
                        self.rc()[role_in_config]['emoji'] = ""

        for role_to_remove in removed_roles:
            del (self.rc()[role_to_remove])

        # update message
        message_text = await self.create_message_text(current_server_roles, ctx)
        message = await self.get_init_msg()

        if message is not None:
            await message.edit(content=message_text)
        else:
            await utils.write_mod_channel(Lang.lang(self, 'creating_init_msg'))
            message = await channel.send(message_text)
            Storage.get(self)['message']['message_id'] = message.id
            self.bot.reaction_listener.register(message, self.update_reaction_based_user_role)

        # remove reactions w/o role
        for reaction in message.reactions:
            reaction_str = emoji.demojize(str(reaction), True)
            for role in self.rc():
                if self.rc()[role]['emoji'] == reaction_str:
                    break
            else:
                await message.clear_reaction(reaction)

        # add reactions for new roles
        for role_config in self.rc():
            emoji_id = self.rc()[role_config]['emoji']
            if not emoji_id:
                continue
            emote = await stringutils.emojize(emoji_id, ctx)
            await message.add_reaction(emote)

        Storage.save(self)

    async def update_reaction_based_user_role(self, event):
        """
        Updates the user roles based on the reaction events.
        :param event: The BaseReactionEvent data
        """

        if event.user == self.bot.user:
            return

        emoji_str = emoji.demojize(str(event.emoji), True)
        update_type = ""
        has_role_update = False
        role = None
        for configured_role in self.rc():
            configured_emoji = self.rc()[configured_role]['emoji']
            if configured_emoji == emoji_str:
                role = discord.utils.get(self.bot.guild.roles, id=configured_role)
                if isinstance(event, reactions.ReactionAddedEvent) and role not in event.member.roles:
                    update_type = "add"
                    await add_user_role(event.member, role)
                    has_role_update = True
                elif isinstance(event, reactions.ReactionRemovedEvent) and role in event.member.roles:
                    update_type = "remove"
                    await remove_user_role(event.member, role)
                    has_role_update = True

        if has_role_update:
            await utils.log_to_mod_channel_without_ctx(**{'Type': "Self-assign role",
                                                          'Action': update_type,
                                                          'User': event.member.mention,
                                                          'Reaction': event.emoji,
                                                          'role': role.mention})

    @commands.group(name="role", aliases=["roles"], invoke_without_command=True)
    async def cmd_role(self, ctx, user: discord.Member, action, role: discord.Role):
        async with ctx.typing():
            if not permchecks.check_mod_access(ctx.author):
                if role.id not in self.rc():
                    raise commands.CheckFailure(message=Lang.lang(self, 'role_user_not_configured'))

                need_mod_role_id = self.rc()[role.id]['modrole']
                if need_mod_role_id is None or need_mod_role_id == 0:
                    raise commands.CheckFailure(message=Lang.lang(self, 'role_user_no_modrole', role.name))

                if need_mod_role_id not in [r.id for r in ctx.author.roles]:
                    raise commands.MissingRole(need_mod_role_id)

            if action.lower() == "add":
                if role in user.roles:
                    await ctx.send(Lang.lang(self, 'role_user_already', converters.get_best_username(user), role))
                    return
                await add_user_role(user, role)
                await ctx.send(Lang.lang(self, 'role_user_added', role, converters.get_best_username(user)))
            elif action.lower() == "del":
                if role not in user.roles:
                    await ctx.send(Lang.lang(self, 'role_user_doesnt_have', converters.get_best_username(user), role))
                    return
                await remove_user_role(user, role)
                await ctx.send(Lang.lang(self, 'role_user_removed', role, converters.get_best_username(user)))
            else:
                raise commands.BadArgument(Lang.lang(self, 'role_user_bad_arg'))

        await utils.log_to_mod_channel(ctx)

    @cmd_role.command(name="add")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_role_add(self, ctx, role_name, emoji_or_modrole="", color: discord.Color = None):
        async with ctx.typing():
            emoji_str = await stringutils.demojize(emoji_or_modrole, ctx)
            try:
                modrole = await commands.RoleConverter().convert(ctx, emoji_or_modrole)
                modrole_id = modrole.id
                emoji_str = ""
            except commands.CommandError:
                modrole_id = 0

            if not emoji_str and modrole_id == 0:
                try:
                    color = await commands.ColourConverter().convert(ctx, emoji_or_modrole)
                except (commands.CommandError, IndexError):
                    color = discord.Color.default()

            try:
                existing_role = await commands.RoleConverter().convert(ctx, role_name)
            except commands.CommandError:
                existing_role = None
            if existing_role is not None:
                if existing_role.id in self.rc():
                    # Update role data
                    if emoji_str:
                        self.rc()[existing_role.id]['emoji'] = emoji_str
                    if modrole_id != 0:
                        self.rc()[existing_role.id]['modrole'] = modrole_id
                    await self.update_role_management(ctx)
                    await ctx.send(Lang.lang(self, 'role_add_updated', role_name))
                else:
                    # role exists on server, but not in config, add it there
                    self.rc()[existing_role.id] = {'emoji': emoji_str, 'modrole': modrole_id}
                    await self.update_role_management(ctx)
                    await ctx.send(Lang.lang(self, 'role_add_config', role_name))
                await utils.log_to_mod_channel(ctx)
                return

            # Execute role add
            new_role = await add_server_role(ctx.guild, role_name, color)
            self.rc()[new_role.id] = {'emoji': emoji_str, 'modrole': modrole_id}
            await self.update_role_management(ctx)
        await ctx.send(Lang.lang(self, 'role_add_created', role_name, color))
        await utils.log_to_mod_channel(ctx)

    @cmd_role.command(name="del")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_role_del(self, ctx, role: discord.Role):
        async with ctx.typing():
            await remove_server_role(role)
            await self.update_role_management(ctx)
        await ctx.send(Lang.lang(self, 'role_del', role.name))
        await utils.log_to_mod_channel(ctx)

    @cmd_role.command(name="untrack")
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_role_untrack(self, ctx, role: discord.Role):
        del (self.rc()[role.id])
        await self.update_role_management(ctx)
        await ctx.send(Lang.lang(self, 'role_untrack', role.name))
        await utils.log_to_mod_channel(ctx)

    @cmd_role.command(name="request")
    async def cmd_role_request(self, ctx, role: discord.Role):
        modrole = None
        for configured_role in self.rc():
            if configured_role == role.id:
                modrole = discord.utils.get(ctx.guild.roles, id=self.rc()[configured_role]['modrole'])
                break

        if modrole is None:
            await ctx.send(Lang.lang(self, 'role_request_no_modrole', role.name))
        else:
            await ctx.send(Lang.lang(self, 'role_request_ping', modrole.mention, ctx.author.mention, role.name))

    @cmd_role.command(name="update", invoke_without_command=True)
    @commands.has_any_role(*Config().MOD_ROLES)
    async def cmd_role_update(self, ctx, *, message=""):
        channel = None
        try:
            channel = await commands.TextChannelConverter().convert(ctx, message)
        except commands.CommandError:
            pass

        if channel is None and len(message) < 2:
            await ctx.send(Lang.lang(self, 'invalid_channel'))
            return

        if channel is not None:
            if self.has_init_msg_set:
                await ctx.send(Lang.lang(self, 'channel_cant_changed'))
            else:
                Storage.get(self)['message']['channel_id'] = channel.id
                await ctx.send(Lang.lang(self, 'channel_updated'))
            return

        if message:
            Storage.get(self)['message']['content'] = message

        Storage.save(self)
        await self.update_role_management(ctx)
        await ctx.send(Lang.lang(self, 'role_update'))
        await utils.log_to_mod_channel(ctx)

    @cmd_role.command(name="msg", aliases=["link"])
    async def cmd_get_msg_cmd(self, ctx):
        msg = await self.get_init_msg()
        if msg is not None:
            await ctx.send(msg.jump_url)
        else:
            await ctx.send(Lang.lang(self, 'not_init_message'))
