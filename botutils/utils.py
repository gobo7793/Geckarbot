import discord
import datetime
import random
from discord.ext.commands.bot import Bot
from conf import Config
import logging


chan_logger = logging.getLogger("channel")


def convert_to_local_time(timestamp):
    """
    Converts the given timestamp from UTC to local time
    :param timestamp: The datetime instance of the timestamp
    """
    return timestamp.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None)


# todo move to ... eh ... parsers?
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


# todo move to converters and rename to something that contains the word "embed"
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
