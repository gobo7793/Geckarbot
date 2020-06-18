import pytz
import discord
import datetime
import emoji
from discord.ext.commands.bot import Bot
from conf import Config
from threading import Thread, Lock
import asyncio
import time
import logging


class HasAlreadyRun(Exception):
    """
    Is raised by AsyncTimer if cancel() comes too late
    """
    def __init__(self, callback):
        super().__init__("Timer callback has already run, callback was {}".format(callback))


class AsyncTimer(Thread):
    def __init__(self, bot, t, callback, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.loop = bot.loop

        self.t = t
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

        self.cancelled = False
        self.has_run = False
        self.cancel_lock = Lock()

        super().__init__()
        self.start()

    def run(self):
        self.logger.debug("Running timer, will be back in {} seconds (callback: {})".format(self.t, self.callback))
        time.sleep(self.t)

        with self.cancel_lock:
            if self.cancelled:
                self.logger.debug("Timer was cancelled (callback: {})".format(self.callback))
                return
            self.has_run = True
            self.logger.debug("Timer over, running callback {}".format(self.callback))

            try:
                asyncio.run_coroutine_threadsafe(self.callback(*self.args, **self.kwargs), self.loop)
            except Exception as e:
                self.logger.error(e)
                raise e

    def cancel(self):
        with self.cancel_lock:
            if self.has_run:
                raise HasAlreadyRun(self.callback)
            self.cancelled = True


def get_best_username(user):
    """
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, discord.User) or user.nick is None:
        return user.name
    return user.nick


def format_andlist(andlist, ands="and", emptylist="nobody"):
    """
    Builds a string such as "a, b, c and d".
    :param andlist: List of elements to be formatted in a string.
    :param ands: "and"-string that sits between the last two users.
    :param emptylist: Returned if andlist is empty.
    :return: String that contains all elements or emptylist if the list was empty.
    """
    if len(andlist) == 0:
        return emptylist

    if len(andlist) == 1:
        return str(andlist[0])

    s = ", ".join(andlist[:-1])
    return "{} {} {}".format(s, ands, andlist[-1])


def clear_link(link):
    """Removes trailing and leading < and > from links"""
    if link.startswith('<'):
        link = link[1:]
    if link.endswith('>'):
        link = link[:-1]
    return link


def convert_to_local_time(timestamp):
    """
    Converts the given timestamp from UTC to local time
    :param datetime: The datetime instance of the timestamp
    """
    return timestamp.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None)

async def emojize(demote_str, ctx):
    """
    Converts the demojized str represantation of the emoji back to an emoji string
    :param demote_str: The string representation of the emoji
    :param ctx: The command context for the discord.py emoji converters
    :return: The emojized string
    """
    try:
        emote = await discord.ext.commands.PartialEmojiConverter().convert(ctx, demote_str)
    except:
        emote = emoji.emojize(demote_str, True)
    return str(emote)

async def demojize(emote, ctx):
    """
    Converts the emojized str of the emoji to its demojized str representation
    :param emote: The msg with the emoji (only the emoji)
    :param ctx: The command context for the discord.py emoji converters
    :return: The demojized string or an empty string if no emoji found
    """
    converted = ""
    try:
        converted = await discord.ext.commands.PartialEmojiConverter().convert(ctx, emote)
    except:
        converted = emoji.demojize(emote, True)
    return str(converted)


async def write_debug_channel(bot: Bot, message):
    """Writes the given message or embed to the debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        if isinstance(message, discord.Embed):
            await debug_chan.send(embed=message)
        else:
            await debug_chan.send(message)


async def write_admin_channel(bot: Bot, message):
    """Writes the given message or embed to the admin channel"""
    admin_chan = bot.get_channel(Config().ADMIN_CHAN_ID)
    if admin_chan is not None:
        if isinstance(message, discord.Embed):
            await admin_chan.send(embed=message)
        else:
            await admin_chan.send(message)

async def log_to_admin_channel_without_ctx(bot, **kwargs):
    """
    Logs the kwargs as embed fileds to the admin channel
    Doesn't log if Config().DEBUG_MODE is True.
    :param context: the key-value-list for the fields
    """
    if Config().DEBUG_MODE == True:
        return

    timestamp = convert_to_local_time(datetime.datetime.now()).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Admin log event")
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
    if Config().DEBUG_MODE == True:
        return

    timestamp = convert_to_local_time(context.message.created_at).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title=context.message.clean_content)
    embed.add_field(name="User", value=context.author.mention)
    embed.add_field(name="Channel", value=context.channel.mention)
    embed.add_field(name="Timestamp", value=timestamp)
    embed.add_field(name="URL", value=context.message.jump_url)

    await write_admin_channel(context.bot, embed)
