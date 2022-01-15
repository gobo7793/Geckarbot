import logging
import re
from typing import Optional, Union

import nextcord
from nextcord.ext import commands

from base.configurable import BasePlugin, NotFound
from base.data import Config

_id_regex = re.compile(r'([0-9]{15,21})$')


logger = logging.getLogger(__name__)


def _get_id_match(argument):
    return _id_regex.match(argument)


def _get_from_guilds(bot, getter, argument):
    result = None
    for guild in bot.guilds:
        result = getattr(guild, getter)(argument)
        if result:
            return result
    return result


def get_best_username(user: Union[nextcord.User, nextcord.Member, str]) -> str:
    """
    Gets the best username for the given user or the str representation of the given object.
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, nextcord.abc.User):
        return user.display_name
    return str(user)


def get_best_user(uid: int) -> Union[nextcord.Member, nextcord.User, None]:
    """
    Gets the member object of the given user id, or if member not found, the user object, or None of nothing found.

    :param uid: The user id from which the member/user object has to be returned
    :return: The member or user object or None if no user found
    """
    result = Config().bot.guild.get_member(uid)
    if result is None:
        result = Config().bot.get_user(uid)
    return result


def get_username_from_id(uid: int) -> Optional[str]:
    """
    Gets the best username from the given user id, or None if user id not found.
    Short: Calls get_best_user() and then get_best_username()

    :param uid: The user id from which the user name should be given
    :return: The best user name or None if user id not found
    """
    user = get_best_user(uid)
    if user is None:
        return None
    return get_best_username(user)


def convert_member(argument) -> Optional[nextcord.Member]:
    # pylint: disable=useless-param-doc
    """
    Tries to convert the given argument to a discord Member object like the Member converter, but w/o context.

    :param argument: The argument to convert
    :return: The Member or None
    :raise commands.BadArgument: If argument is no valid Member
    """
    match = argument if isinstance(argument, int) else _get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
    guild = Config().bot.guild
    result = None
    if match is None:
        # not a mention...
        if guild:
            result = guild.get_member_named(argument)
        else:
            result = _get_from_guilds(Config().bot, 'get_member_named', argument)
    else:
        user_id = match if isinstance(match, int) else int(match.group(1))
        if guild:
            result = guild.get_member(user_id)

    if result is None:
        raise commands.BadArgument('Member "{}" not found'.format(argument))

    return result


def get_plugin_by_name(name: str) -> Optional[BasePlugin]:
    """
    :param name: Name of the plugin that is to be returned.
    :return: Configurable object of the plugin with name `name`. Returns None if no such plugin is found.
    """
    for el in Config().bot.plugins:
        if el.get_name() == name:
            return el
    return None


def get_embed_str(embed: Union[nextcord.Embed, str]) -> Union[nextcord.Embed, str]:
    """
    Returns the given embed contents as loggable string.
    If embed is no embed object, the str of the object will be returned.

    :param embed: The embed
    :return: The loggable string
    """

    if not isinstance(embed, nextcord.Embed):
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


def serialize_channel(channel: Union[nextcord.DMChannel, nextcord.TextChannel],
                      author_id: Optional[int] = None) -> dict:
    """
    Serializes channel into a dict that can be deserialized by deserialize_channel().

    :param channel: Channel to be serialized. Currently only supports `DMChannel` and `TextChannels`.
    :param author_id: id of the user whose DM channel this might be (usually context author). Set this on initial
        serialization of a channel.
    :return: dict{type: typestring, id: id}
    :raises RuntimeError: If channel is of a type that is not supported
    """
    if isinstance(channel, nextcord.DMChannel):
        recipient_id = channel.recipient.id if channel.recipient is not None else author_id
        if recipient_id is None:
            raise RuntimeError("DMChannel serialization: Recipient ID not present")
        return {
            "type": "dm",
            "id": recipient_id
        }

    if isinstance(channel, nextcord.TextChannel):
        return {
            "type": "text",
            "id": channel.id
        }

    if isinstance(channel, nextcord.Thread):
        return {
            "type": "thread",
            "id": channel.id
        }

    raise RuntimeError("Channel {} not supported".format(channel))


async def deserialize_channel(channeldict: dict) -> Union[nextcord.DMChannel, nextcord.TextChannel, nextcord.Thread]:
    """
    Deserializes channel from a dict that was created by serialize_channel.

    :param channeldict: dict created by serialize_channel
    :return: Channel that was serialized before
    :raises NotFound: If the channel could not be found for whatever reason
    """
    if channeldict["type"] == "dm":
        user = get_best_user(channeldict["id"])
        if user is None:
            raise NotFound
        r = user.dm_channel
        if r is None:
            r = await user.create_dm()
        if r.recipient is None:
            logger.debug("Deserialize DM Channel: Setting recipient")
            r.recipient = user
        return r

    if channeldict["type"] == "text":
        r = Config().bot.guild.get_channel(channeldict["id"])
        if r is None:
            raise NotFound
        return r

    if channeldict["type"] == "thread":
        r = Config().bot.guild.get_thread(channeldict["id"])
        if r is None:
            raise NotFound
        return r

    raise NotFound("type: {}, id: {}".format(channeldict["type"], channeldict["id"]))
