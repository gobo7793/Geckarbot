import pytz
import discord
import datetime
from discord.ext.commands.bot import Bot
from conf import Config


def get_best_username(user):
    """
    :param user: User (Member or User instance) that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if isinstance(user, discord.User) or user.nick is None:
        return user.name
    return user.nick


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


async def log_to_admin_channel(context):
    """
    Logs the context to admin channel with following content:
    Author name, Timestamp, Channel name, Message
    :param bot: The bot
    :param context: The context to log to the admin channel
    """
    author_field = "{}#{} in {}".format(context.author.name, context.author.discriminator, context.channel.name)
    timestamp = convert_to_local_time(context.message.created_at)

    embed = discord.Embed(title=context.message.clean_content)
    embed.set_author(name=author_field)
    embed.timestamp = timestamp
    embed.description = context.message.jump_url

    await write_admin_channel(context.bot, embed)
