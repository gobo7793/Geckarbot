from typing import Union

import discord
import datetime
import random
from discord.ext.commands.bot import Bot

from botutils.converters import get_embed_str
from botutils.timeutils import to_local_time
from botutils.stringutils import paginate
from conf import Config
import logging

chan_logger = logging.getLogger("channel")


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


async def _write_to_channel(bot: Bot, channel_id: int = 0, message: Union[str, discord.Embed] = None,
                            channel_type: str = ""):
    """
    Writes a message to a channel and logs the message

    :param bot: The bot
    :param channel_id: The channel ID of the channel to send a message to
    :param message: The message or embed to send
    :param channel_type: The channel type or name for the logging output
    """

    channel = bot.get_channel(channel_id)
    if not Config().DEBUG_MODE and channel is not None and message is not None and message:
        if isinstance(message, discord.Embed):
            paginate_embed(message)
            await channel.send(embed=message)
        else:
            messages = message.split("\n")
            for msg in paginate(messages, delimiter="\n"):
                if len(msg) > 2000:
                    msg = f"{msg[0:1998]} …"
                await channel.send(msg)

    log_msg = get_embed_str(message)
    chan_logger.info(f"{channel_type} : {log_msg}")


async def write_debug_channel(bot: Bot, message):
    """Writes the given message or embed to the debug channel"""
    await _write_to_channel(bot, Config().DEBUG_CHAN_ID, message, "debug")


async def write_admin_channel(bot: Bot, message):
    """Writes the given message or embed to the admin channel"""
    await _write_to_channel(bot, Config().ADMIN_CHAN_ID, message, "admin")


async def log_to_admin_channel_without_ctx(bot, **kwargs):
    """
    Logs the kwargs as embed fileds to the admin channel
    Doesn't log if Config().DEBUG_MODE is True.
    :param bot: the bot instance
    :param kwargs: the key-value-list for the fields
    """
    timestamp = to_local_time(datetime.datetime.now()).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Admin log event")
    embed.add_field(name="Timestamp", value=timestamp)
    for key, value in kwargs.items():
        embed.add_field(name=str(key), value=str(value))

    await write_admin_channel(bot, embed)


async def log_to_admin_channel(context):
    """
    Logs the context to admin channel with following content:
    Author name, Timestamp, Channel name, Message.
    Doesn't log if Config().DEBUG_MODE is True.
    :param context: The context to log to the admin channel
    """
    timestamp = to_local_time(context.message.created_at).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Special command used")
    embed.description = context.message.clean_content
    embed.add_field(name="User", value=context.author.mention)
    embed.add_field(name="Channel", value=context.channel.mention)
    embed.add_field(name="Timestamp", value=timestamp)
    embed.add_field(name="URL", value=context.message.jump_url)

    await write_admin_channel(context.bot, embed)


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
