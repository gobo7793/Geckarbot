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


async def convert_member(bot, message, argument):
    """
    Tries to convert the given argument to a discord Member object like the Member converter, but w/o context.

    :param bot: The bot
    :param message: The message
    :param argument: The argument to convert
    :return: The Member or None
    """
    match = _get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
    guild = message.guild
    result = None
    if match is None:
        # not a mention...
        if guild:
            result = guild.get_member_named(argument)
        else:
            result = _get_from_guilds(bot, 'get_member_named', argument)
    else:
        user_id = int(match.group(1))
        if guild:
            result = guild.get_member(user_id) or discord.utils.get(message.mentions, id=user_id)
        else:
            result = _get_from_guilds(bot, 'get_member', user_id)

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
