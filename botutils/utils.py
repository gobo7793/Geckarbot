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
    Gets the best username for the given user or the str representation of the given object.
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, discord.abc.User):
        return user.display_name
    return str(user)


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


def get_embed_content_str(embed: discord.Embed):
    """Returns the given embed contents as loggable string"""
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


async def write_debug_channel(bot: Bot, message):
    """Writes the given message or embed to the debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        log_msg = message
        if isinstance(message, discord.Embed):
            await debug_chan.send(embed=message)
            log_msg = get_embed_content_str(message)
        else:
            await debug_chan.send(message)

        logging.info("Written to debug chan: " + log_msg)


async def write_admin_channel(bot: Bot, message):
    """Writes the given message or embed to the admin channel"""
    admin_chan = bot.get_channel(Config().ADMIN_CHAN_ID)
    if admin_chan is not None:
        log_msg = message
        if isinstance(message, discord.Embed):
            await admin_chan.send(embed=message)
            log_msg = get_embed_content_str(message)
        else:
            await admin_chan.send(message)

        logging.info("Written to admin chan: " + log_msg)


async def log_to_admin_channel_without_ctx(bot, **kwargs):
    """
    Logs the kwargs as embed fileds to the admin channel
    Doesn't log if Config().DEBUG_MODE is True.
    :param bot: the bot instance
    :param kwargs: the key-value-list for the fields
    """
    if Config().DEBUG_MODE:
        return

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
    if Config().DEBUG_MODE:
        return

    timestamp = convert_to_local_time(context.message.created_at).strftime('%d.%m.%Y, %H:%M')

    embed = discord.Embed(title="Special command used")
    embed.description = context.message.clean_content
    embed.add_field(name="User", value=context.author.mention)
    embed.add_field(name="Channel", value=context.channel.mention)
    embed.add_field(name="Timestamp", value=timestamp)
    embed.add_field(name="URL", value=context.message.jump_url)

    await write_admin_channel(context.bot, embed)


def paginate(items, prefix="", suffix="", msg_prefix="", delimiter="\n", f=lambda x: x):
    """
    Generator for pagination. Compiles the entries in `items` into strings that are shorter than 2000 (discord max
    message length). If a single item is longer than 2000, it is put into its own message. 
    :param items: List of items that are to be put into message strings
    :param prefix: The first message has this prefix.
    :param suffix: The last message has this suffix.
    :param msg_prefix: Every message has this prefix.
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
            print("yielding1 {}".format(to_add))
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
            print("yielding2 {}".format(delimiter.join(current_msg)))
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
        print("yielding3 {}".format(current_msg))
        yield current_msg
        print("yielding4 {}".format(suffix))
        yield suffix
    else:
        r = current_msg + suffix
        if not r.strip() == "":
            print("yielding5 {}".format(r))
            yield r
