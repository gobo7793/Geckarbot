import re

import discord
from discord.ext import commands


_id_regex = re.compile(r'([0-9]{15,21})$')


def _get_id_match(argument):
    return _id_regex.match(argument)


def _get_from_guilds(bot, getter, argument):
    result = None
    for guild in bot.guilds:
        result = getattr(guild, getter)(argument)
        if result:
            return result
    return result


def get_best_username(user):
    """
    Gets the best username for the given user or the str representation of the given object.
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, discord.abc.User):
        return user.display_name
    return str(user)


def convert_member(bot, argument):
    """
    Tries to convert the given argument to a discord Member object like the Member converter, but w/o context.

    :param bot: The bot
    :param argument: The argument to convert
    :return: The Member or None
    """
    print("isint: {}".format(isinstance(argument, int)))
    match = argument if isinstance(argument, int) else _get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
    guild = bot.guild
    result = None
    if match is None:
        # not a mention...
        if guild:
            result = guild.get_member_named(argument)
        else:
            result = _get_from_guilds(bot, 'get_member_named', argument)
    else:
        user_id = match if isinstance(match, int) else int(match.group(1))
        if guild:
            result = guild.get_member(user_id)

    if result is None:
        raise commands.BadArgument('Member "{}" not found'.format(argument))

    return result


def get_plugin_by_name(bot, name):
    """
    :param bot: Geckarbot reference
    :param name: Name of the plugin that is to be returned.
    :return: Configurable object of the plugin with name `name`. Returns None if no such plugin is found.
    """
    for pluginslot in bot.plugins:
        if pluginslot.name == name:
            return pluginslot.instance
    return None


def get_plugin_container(bot, plugin):
    """
    :param bot: Geckarbot instance
    :param plugin: BasePlugin instance
    :return: PluginContainer whose instance is `plugin`
    """
    for plugin_cnt in bot.plugins:
        if plugin_cnt.instance == plugin:
            return plugin_cnt
    return None


def get_embed_str(embed):
    """
    Returns the given embed contents as loggable string.
    If embed is no embed object, the str of the object will be returned.

    :param embed: The embed
    :return: The loggable string
    """

    if not isinstance(embed, discord.Embed):
        return str(embed)

    m = ""
    if embed.title is not None and embed.title:
        m += "Embed Title: " + embed.title
    if embed.author is not None and embed.author:
        m += ", Author: " + embed.author
    if embed.description is not None and embed.description:
        m += ", Description: " + embed.description
    if embed.url is not None and embed.url:
        m += ", URL: " + embed.url
    if embed.footer is not None and embed.footer:
        m += ", Footer: " + embed.footer
    if embed.timestamp is not None and embed.timestamp:
        m += ", Timestamp: " + str(embed.timestamp)
    for f in embed.fields:
        m += ", Field {}={}".format(f.name, f.value)

    return m
