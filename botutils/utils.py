from typing import Union

import datetime
import random
import inspect
import logging
import discord

from base import NotFound
from data import Config
from botutils.converters import get_embed_str
from botutils.timeutils import to_local_time
from botutils.stringutils import paginate

chan_logger = logging.getLogger(__name__)


async def add_reaction(message: discord.Message, reaction):
    """
    Adds a reaction to the message, or if not possible, post the reaction in an own message.

    :param message: The message to react
    :param reaction: The reaction, can be a unicode emoji,
                     discord.Emoji, discord.PartialEmoji or discord.Reaction
    """
    try:
        await message.add_reaction(reaction)
    except discord.HTTPException:
        await message.channel.send(reaction)


def paginate_embed(embed: discord.Embed):
    """
    Paginates/Cuts to long embed contents in title and description of the embed.
    If the Embeds exceed after that 6000 chars an Exception is thrown.
    :param embed: The embed to paginate
    :return: The paginated embed
    """
    # Limit overview see https://discordjs.guide/popular-topics/embeds.html#notes
    if len(embed.title) > 256:
        embed.title = f"{embed.title[0:254]} …"
    if len(embed.description) > 2048:
        if embed.description.endswith("```"):
            embed.description = f"{embed.description[0:2043]}```\n…"
        else:
            embed.description = f"{embed.description[0:2046]} …"
    if len(embed) > 6000:
        raise Exception(f"Embed is still to long! Title: {embed.title}")


async def _write_to_channel(channel_id: int = 0, message: Union[str, discord.Embed] = None,
                            channel_type: str = ""):
    """
    Writes a message to a channel and logs the message..
    Doesn't write if DEBUG_MODE is True.

    :param channel_id: The channel ID of the channel to send a message to
    :param message: The message or embed to send
    :param channel_type: The channel type or name for the logging output
    """
    log_msg = get_embed_str(message)
    chan_logger.info(f"%s : %s", channel_type, log_msg)

    channel = Config().bot.get_channel(channel_id)
    if not Config().bot.DEBUG_MODE and channel is not None and message is not None and message:
        if isinstance(message, discord.Embed):
            paginate_embed(message)
            await channel.send(embed=message)
        else:
            messages = message.split("\n")
            for msg in paginate(messages, delimiter="\n"):
                if len(msg) > 2000:
                    msg = f"{msg[0:1998]} …"
                await channel.send(msg)


async def write_debug_channel(message: Union[str, discord.Embed]):
    """
    Writes the given message or embed to the debug channel.
    Doesn't write if DEBUG_MODE is True.

    :param message: The message or embed to write
    """
    await _write_to_channel(Config().bot.DEBUG_CHAN_ID, message, "debug")


async def write_admin_channel(message: Union[str, discord.Embed]):
    """
    Writes the given message or embed to the admin channel.
    Doesn't write if DEBUG_MODE is True.

    :param message: The message or embed to write
    """
    await _write_to_channel(Config().bot.ADMIN_CHAN_ID, message, "admin")


async def write_mod_channel(message: Union[str, discord.Embed]):
    """
    Writes the given message or embed to the mod channel.
    Doesn't write if DEBUG_MODE is True.

    :param message: The message or embed to write
    """
    await _write_to_channel(Config().bot.MOD_CHAN_ID, message, "mod")


async def _log_without_ctx_to_channel(func, **kwargs):
    """
    Performs the log_to_..._channel_without_ctx and writes to channel using func.
    func must be the signature async def func(message/embed).
    """
    timestamp = to_local_time(datetime.datetime.now()).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Log event")
    embed.add_field(name="Timestamp", value=timestamp)
    for key, value in kwargs.items():
        embed.add_field(name=str(key), value=str(value))

    await func(embed)


async def log_to_debug_channel_without_ctx(**kwargs):
    """
    Logs the kwargs as embed fields to the debug channel.
    Doesn't log if DEBUG_MODE is True.

    :param kwargs: the key-value-list for the fields
    """
    await _log_without_ctx_to_channel(write_debug_channel, **kwargs)


async def log_to_admin_channel_without_ctx(**kwargs):
    """
    Logs the kwargs as embed fields to the admin channel.
    Doesn't log if DEBUG_MODE is True.

    :param kwargs: the key-value-list for the fields
    """
    await _log_without_ctx_to_channel(write_admin_channel, **kwargs)


async def log_to_mod_channel_without_ctx(**kwargs):
    """
    Logs the kwargs as embed fields to the mod channel.
    Doesn't log if DEBUG_MODE is True.

    :param kwargs: the key-value-list for the fields
    """
    await _log_without_ctx_to_channel(write_mod_channel, **kwargs)


async def _log_to_channel(context, func):
    """
    Writes the given context using func.
    func must be the signature async def func(message/embed).
    """
    timestamp = to_local_time(context.message.created_at).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Special command used")
    embed.description = context.message.clean_content
    embed.add_field(name="User", value=context.author.mention)
    embed.add_field(name="Channel", value=context.channel.mention)
    embed.add_field(name="Timestamp", value=timestamp)
    embed.add_field(name="URL", value=context.message.jump_url)

    await func(embed)


async def log_to_debug_channel(context):
    """
    Logs the context to debug channel with following content:
    Author name, Timestamp, Channel name, Message.
    Doesn't log if DEBUG_MODE is True.

    :param context: The context to log
    """
    await _log_to_channel(context, write_debug_channel)


async def log_to_admin_channel(context):
    """
    Logs the context to admin channel with following content:
    Author name, Timestamp, Channel name, Message.
    Doesn't log if DEBUG_MODE is True.

    :param context: The context to log
    """
    await _log_to_channel(context, write_admin_channel)


async def log_to_mod_channel(context):
    """
    Logs the context to mod channel with following content:
    Author name, Timestamp, Channel name, Message.
    Doesn't log if DEBUG_MODE is True.

    :param context: The context to log
    """
    await _log_to_channel(context, write_mod_channel)


def sort_commands_helper(commands, order):
    """
    Sorts a list of commands in place according to a list of command names. If a command has no corresponding
    command name in `order`, it is removed from the list.
    :param commands: List of commands that is to be ordered
    :param order: Ordered list of command names
    :return: Sorted command list
    """
    r = []
    for el in order:
        for cmd in commands:
            if cmd.name == el:
                r.append(cmd)
                break
    return r


def trueshuffle(p):
    """
    Shuffles a list in place so that no element is at the index where it was before. Fails on lists of length < 2.
    :param p: List to shuffle
    """
    orig = p.copy()
    for toswap_i in range(len(p)):
        # find swap targets that do not violate "total swap" / "new home" condition
        k = []
        for target in range(len(p)):
            if orig[target] == p[toswap_i] or orig[toswap_i] == p[target]:
                k.append(target)

        choosefrom = [m for m in range(len(p)) if m not in k]
        choice = random.choice(choosefrom)
        toswap = p[toswap_i]
        p[toswap_i] = p[choice]
        p[choice] = toswap


async def execute_anything(f, *args, **kwargs):
    """
    Executes functions, coroutine functions and coroutines, returns their return values and raises their exceptions.
    :param f: Function, coroutine function or coroutine to execute / schedule
    :param args: args to pass to f
    :param kwargs: kwargs to pass to f
    :return: Return value of f
    """
    if inspect.iscoroutinefunction(f):
        f = f(*args, **kwargs)
    if inspect.iscoroutine(f):
        # loop = asyncio.get_event_loop()
        # task = loop.create_task(f)
        # loop.run_until_complete(task)
        # e = task.exception()
        # if e is not None:
        #     raise e
        # return task.result()
        return await f
    return f(*args, **kwargs)


def get_plugin_by_cmd(cmd):
    """
    Returns the plugin object which contains the given command

    :param cmd: The command object
    :return: The plugin which contains the command
    """
    for plugin in Config().bot.plugins:
        for el in plugin.get_commands():
            if el == cmd:
                return plugin
    raise NotFound
