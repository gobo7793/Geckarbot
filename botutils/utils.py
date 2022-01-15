from typing import Union, Optional, Coroutine, Any, Callable
import datetime
import random
import inspect
import logging
import asyncio
import traceback

from nextcord import Embed, HTTPException, Message, TextChannel, DMChannel, GroupChannel, User
from nextcord.ext.commands import Command, Context

from base.configurable import NotFound, BasePlugin, Configurable
from base.data import Config, Lang
from botutils.converters import get_embed_str, get_best_username
from botutils.timeutils import to_local_time
from botutils.stringutils import paginate

log = logging.getLogger(__name__)


async def add_reaction(message: Message, reaction):
    """
    Adds a reaction to the message, or if not possible, post the reaction in an own message.

    :param message: The message to react
    :param reaction: The reaction, can be a unicode emoji,
                     discord.Emoji, discord.PartialEmoji or discord.Reaction
    """
    try:
        await message.add_reaction(reaction)
    except HTTPException:
        await message.channel.send(reaction)


def paginate_embed(embed: Embed):
    """
    Paginates/Cuts to long embed contents in title and description of the embed.
    If the Embeds exceed after that 6000 chars an Exception is thrown.

    :param embed: The embed to paginate
    :exception Exception: If embed is still to long
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


async def _write_to_channel(channel_id: int = 0, message: Union[str, Embed] = None,
                            channel_type: str = ""):
    """
    Writes a message to a channel and logs the message..
    Doesn't write if DEBUG_MODE is True.

    :param channel_id: The channel ID of the channel to send a message to
    :param message: The message or embed to send
    :param channel_type: The channel type or name for the logging output
    """
    log_msg = get_embed_str(message)
    log.info("%s : %s", channel_type, log_msg)

    channel = Config().bot.get_channel(channel_id)
    if not Config().bot.DEBUG_MODE and channel is not None and message is not None and message:
        if isinstance(message, Embed):
            paginate_embed(message)
            await channel.send(embed=message)
        else:
            messages = message.split("\n")
            for msg in paginate(messages, delimiter="\n"):
                if len(msg) > 2000:
                    msg = f"{msg[0:1998]} …"
                await channel.send(msg)


async def write_debug_channel(message: Union[str, Embed]):
    """
    Writes the given message or embed to the debug channel.
    Doesn't write if DEBUG_MODE is True.

    :param message: The message or embed to write
    """
    await _write_to_channel(Config().bot.DEBUG_CHAN_ID, message, "debug")


async def write_admin_channel(message: Union[str, Embed]):
    """
    Writes the given message or embed to the admin channel.
    Doesn't write if DEBUG_MODE is True.

    :param message: The message or embed to write
    """
    await _write_to_channel(Config().bot.ADMIN_CHAN_ID, message, "admin")


async def write_mod_channel(message: Union[str, Embed]):
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

    embed = Embed(title="Log event")
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

    embed = Embed(title="Special command used")
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


async def log_exception(exception, context: Optional[Context] = None, title=":x: Command Error", fields: dict = None):
    """
    Logs an exception to the debug channel, including traceback.

    :param exception: Exception to be logged
    :param context: Context; used to fill context-dependent fields (command, msg, author etc)
    :param title: Embed title
    :param fields: Additional embed fields (field: value)
    """
    embed = Embed(title=title, colour=0xe74c3c)  # Red
    embed.add_field(name='Error', value=exception)

    if context:
        embed.add_field(name='Command', value=context.command)
        embed.add_field(name='Message', value=context.message.clean_content)
        if isinstance(context.channel, TextChannel):
            embed.add_field(name='Channel', value=context.channel.name)
        if isinstance(context.channel, DMChannel):
            embed.add_field(name='Channel', value='DM Channel')
        if isinstance(context.channel, GroupChannel):
            embed.add_field(name='Channel', value=context.channel.recipients)
        embed.add_field(name='Author', value=context.author.display_name)
        embed.url = context.message.jump_url

    if fields:
        for name, value in fields.items():
            embed.add_field(name=str(name), value=str(value))

    embed.timestamp = datetime.datetime.utcnow()

    # gather traceback
    ex_tb = "".join(traceback.TracebackException.from_exception(exception).format())
    is_tb_own_msg = len(ex_tb) > 2000
    if is_tb_own_msg:
        embed.description = "Exception Traceback see next message."
        ex_tb = paginate(ex_tb.split("\n"), msg_prefix="```python\n", msg_suffix="```")
    else:
        embed.description = f"```python\n{ex_tb}```"

    # send messages
    await write_debug_channel(embed)
    if is_tb_own_msg:
        for msg in ex_tb:
            await write_debug_channel(msg)


def sort_commands_helper(commands: list, order: list) -> list:
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


def trueshuffle(p: list):
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


async def coro_wrapper(coro: Coroutine):
    """
    Executes coro and logs exceptions to the debug channel.

    :param coro: Coroutine that is ready to be awaited.
    """
    # pylint: disable=broad-except
    try:
        await coro
    except Exception as e:
        await log_exception(e, title=":x: Task error")


def execute_anything_sync(f: Union[Callable, Coroutine], *args, **kwargs) -> Any:
    """
    Executes functions, coroutine functions and coroutines, returns their return values and raises their exceptions.

    :param f: Function, coroutine function or coroutine to execute / schedule
    :param args: args to pass to f
    :param kwargs: kwargs to pass to f
    :return: If f is a function: Return value of f; if f is a coroutine: task that was created
    """
    if inspect.iscoroutinefunction(f):
        f = f(*args, **kwargs)
    if inspect.iscoroutine(f):
        return asyncio.get_event_loop().create_task(coro_wrapper(f))
    return f(*args, **kwargs)


async def execute_anything(f: Union[Callable, Coroutine], *args, **kwargs) -> Any:
    """
    Executes functions, coroutine functions and coroutines, returns their return values and raises their exceptions.

    :param f: Function, coroutine function or coroutine to execute / schedule
    :param args: args to pass to f
    :param kwargs: kwargs to pass to f
    :return: Return value of f if wait is True; otherwise task object (in coro case)
    """
    if inspect.iscoroutinefunction(f):
        f = f(*args, **kwargs)
    if inspect.iscoroutine(f):
        return await f
    return f(*args, **kwargs)


def get_plugin_by_cmd(cmd: Command) -> BasePlugin:
    """
    Returns the plugin object which contains the given command

    :param cmd: The command object
    :return: The plugin which contains the command
    :raises NotFound: If no plugin contains the given command
    """
    for plugin in Config().bot.plugins:
        for el in plugin.get_commands():
            if el == cmd:
                return plugin
    raise NotFound


def helpstring_helper(plugin: Configurable, command: Command, prefix: str) -> str:
    """
    Helper to retrieve help strings (help, description etc) from a plugin's lang file.
    The lang identifier is expected to be of the format `"prefix_command_subcommand"`,
    e.g. `"usage_command_subcommand"` or `"desc_command"`.
    Raises NotFound according to interface.

    :param plugin: Plugin reference
    :param command: Command that a usage string is requested for.
    :param prefix: Helpstring prefix
    :return: Retrieved help string
    :raises NotFound: Raised to indicate that nothing was found.
    """
    langstr = Lang.lang_no_failsafe(plugin, "{}_{}".format(prefix, command.qualified_name.replace(" ", "_")))
    if langstr is not None:
        return langstr
    raise NotFound()


async def send_dm(user: User, msg: str, raise_exception: bool = False):
    """
    Sends a DM to a user. If the DM channel does not exist, it is created. Logs to debug channel on Exception.
    :param user: User to send a DM to
    :param msg: Message to send
    :param raise_exception: If True, raises the exception instead of logging it.
    """
    chan = user.dm_channel
    if chan is None:
        chan = await user.create_dm()

    try:
        await chan.send(msg)
    except Exception as e:
        if raise_exception:
            raise e
        fields = {"DM recipient": get_best_username(user)}
        await log_exception(e, title=":x: DM Error", fields=fields)
