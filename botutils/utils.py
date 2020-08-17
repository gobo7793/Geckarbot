import discord
import datetime
import emoji
import random
import warnings
from discord.ext.commands.bot import Bot
from conf import Config
from threading import Thread, Lock
import asyncio
import time
import logging


chan_logger = logging.getLogger("channel")


class HasAlreadyRun(Exception):
    """
    Is raised by AsyncTimer if cancel() comes too late
    """

    def __init__(self, callback):
        super().__init__("Timer callback has already run, callback was {}".format(callback))


class AsyncTimer(Thread):
    def __init__(self, bot, t, callback, *args, **kwargs):
        warnings.warn("utils.AsyncTimer is deprecated.")
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
    Gets the best username for the given user or the str representation of the given object.
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, discord.abc.User):
        return user.display_name
    return str(user)


def format_andlist(andlist, ands="and", emptylist="nobody", fulllist="everyone", fulllen=None):
    """
    Builds a string such as "a, b, c and d".
    :param andlist: List of elements to be formatted in a string.
    :param ands: "and"-string that sits between the last two users.
    :param emptylist: Returned if andlist is empty.
    :param fulllist: Returned if andlist has length fulllen.
    :param fulllen: Length of the full andlist. Useful to say "everyone" instead of listing everyone.
    :return: String that contains all elements or emptylist if the list was empty.
    """
    if fulllen is not None and len(andlist) == fulllen:
        return fulllist

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
    :param timestamp: The datetime instance of the timestamp
    """
    return timestamp.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None)


def analyze_time_input(*args):
    """
    Analyzes the given command args for following syntax and returns a datetime object after duration or on given
    date and/or time. If no duration unit (trailing m, h, d in arg[0]), minutes will be used.
    If no date and time can be determined, datetime.max will be returned.
    If for given date/time input some is missing, the current time, date or year will be used.

    [#|#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]

    :param args: The command args for duration/date/time
    :returns: The datetime object with the given date and time or datetime.max
    """
    now = datetime.datetime.now()
    arg = " ".join(args)

    try:  # duration: #|#m|#h|#d
        if arg.endswith("m"):
            return now + datetime.timedelta(minutes=int(arg[:-1]))
        elif arg.endswith("h"):
            return now + datetime.timedelta(hours=int(arg[:-1]))
        elif arg.endswith("d"):
            return now + datetime.timedelta(days=int(arg[:-1]))
        else:
            return now + datetime.timedelta(minutes=int(arg))
    except ValueError:
        try:  # date: DD.MM.YYYY
            parsed = datetime.datetime.strptime(arg, "%d.%m.%Y")
            return datetime.datetime.combine(parsed.date(), now.time())
        except ValueError:
            try:  # time: HH:MM
                parsed = datetime.datetime.strptime(arg, "%H:%M")
                return datetime.datetime.combine(now.date(), parsed.time())
            except ValueError:
                try:  # full datetime: DD.MM.YYYY HH:MM
                    return datetime.datetime.strptime(arg, "%d.%m.%Y %H:%M")
                except ValueError:
                    try:  # datetime w/o year: DD.MM. HH:MM
                        parsed = datetime.datetime.strptime(arg, "%d.%m. %H:%M")
                        return datetime.datetime(now.year, parsed.month, parsed.day, parsed.hour, parsed.minute)
                    except ValueError:
                        pass

    # No valid time input
    return datetime.datetime.max


async def emojize(demote_str, ctx):
    """
    Converts the demojized str represantation of the emoji back to an emoji string
    :param demote_str: The string representation of the emoji
    :param ctx: The command context for the discord.py emoji converters
    :return: The emojized string
    """
    try:
        emote = await discord.ext.commands.PartialEmojiConverter().convert(ctx, demote_str)
    except discord.ext.commands.CommandError:
        emote = emoji.emojize(demote_str, True)
    return str(emote)


async def demojize(emote, ctx):
    """
    Converts the emojized str of the emoji to its demojized str representation
    :param emote: The msg with the emoji (only the emoji)
    :param ctx: The command context for the discord.py emoji converters
    :return: The demojized string or an empty string if no emoji found
    """
    try:
        converted = await discord.ext.commands.PartialEmojiConverter().convert(ctx, emote)
    except discord.ext.commands.CommandError:
        converted = emoji.demojize(emote, True)
    return str(converted)


def get_loggable_str(embed):
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


async def _write_to_channel(bot: Bot, channel_id: int = 0, message=None, channel_type: str = ""):
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
            await channel.send(embed=message)
        else:
            await channel.send(message)

    log_msg = get_loggable_str(message)
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
    timestamp = convert_to_local_time(datetime.datetime.now()).strftime('%d.%m.%Y, %H:%M')

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
    timestamp = convert_to_local_time(context.message.created_at).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Special command used")
    embed.description = context.message.clean_content
    embed.add_field(name="User", value=context.author.mention)
    embed.add_field(name="Channel", value=context.channel.mention)
    embed.add_field(name="Timestamp", value=timestamp)
    embed.add_field(name="URL", value=context.message.jump_url)

    await write_admin_channel(context.bot, embed)


def paginate(items, prefix="", suffix="", msg_prefix="", msg_suffix="", delimiter="\n", f=lambda x: x):
    threshold = 1900
    current_msg = []
    remaining = None
    first = True

    i = 0
    while i != len(items):
        if remaining is None:
            item = str(f(items[i]))
        else:
            item = remaining
            remaining = None

        # Build potential prefix and suffix of this message candidate
        _prefix = msg_prefix
        if first:
            _prefix = prefix + msg_prefix
        _suffix = msg_suffix
        if i == len(items) - 1:
            _suffix = msg_suffix + suffix

        # Split item if too large
        if len(item) + len(_prefix) + len(_suffix) > threshold:
            _suffix = msg_suffix
            li = len(item) + len(_prefix) + len(_suffix)
            item = item[:li]
            remaining = item[li:]

            # Handle message that was accumulated so far
            if current_msg:
                yield "".join(current_msg) + msg_suffix

            # Handle the split message
            yield _prefix + item + _suffix
            first = False
            continue

        so_far = delimiter.join(current_msg)
        if len(_prefix + so_far + delimiter + item + _suffix) > threshold or i == len(items) - 1:
            yield _prefix + so_far + _suffix
            first = False
            current_msg = []
        else:
            current_msg.append(item)

        i += 1


def paginate_old(items, prefix="", suffix="", msg_prefix="", msg_suffix="", delimiter="\n", f=lambda x: x):
    """
    Generator for pagination. Compiles the entries in `items` into strings that are shorter than 2000 (discord max
    message length). If a single item is longer than 2000, it is put into its own message. 
    :param items: List of items that are to be put into message strings
    :param prefix: The first message has this prefix.
    :param suffix: The last message has this suffix.
    :param msg_prefix: Every message has this prefix.
    :param msg_suffix: Every message has this suffix.
    :param delimiter: Delimiter for the list entries.
    :param f: function that is invoked on every `items` entry.
    :return: 
    """
    threshold = 1900
    current_msg = []
    first = True
    for i in items:
        to_add = str(f(i))
        if len(to_add) > threshold:  # really really long entry
            yield to_add
            continue

        if first:
            first = False
            to_add = prefix + to_add

        # sum up current len
        length = 0
        for k in current_msg:
            length += len(k) + len(delimiter)

        if length + len(to_add) > threshold:
            yield delimiter.join(current_msg)
            current_msg = [msg_prefix + to_add]
        else:
            current_msg.append(to_add)

    # Empty list
    if first:
        r = prefix + suffix
        if r.strip() != "":
            yield r

    # Handle last msg
    current_msg = delimiter.join(current_msg)
    if len(current_msg) + len(suffix) > threshold:
        yield current_msg
        yield suffix
    else:
        r = current_msg + suffix
        if not r.strip() == "":
            yield r


def sg_pl(number, singular, plural):
    if number == 1:
        return singular
    return plural


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
