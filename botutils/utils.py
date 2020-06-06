from discord.ext.commands.bot import Bot
from conf import Config
from threading import Thread
import asyncio


class CancelMe:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


async def AsyncTimer(timeout, callback, *args, **kwargs):
    await asyncio.sleep(timeout)
    await callback(*args, **kwargs)
    return CancelMe()


class AsyncTimer3:
    def __init__(self, timeout, callback, *args, **kwargs):
        self.timeout = timeout
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.task = asyncio.ensure_future(self.job())

    async def job(self):
        print("========= Running timer; timeout: {}".format(self.timeout))
        await asyncio.sleep(self.timeout)
        print("========= Timer done")
        await self.callback(*self.args, **self.kwargs)
        print("========= Callback done")

    def cancel(self):
        self.task.cancel()


class AsyncTimer2(Thread):
    def __init__(self, t, callback, *args, **kwargs):
        """
        Timer for coroutines in async or sync contexts.
        :param t: Time that is waited before calling callback in seconds
        :param callback: Callback coroutine that is called with all following args and keyword args.
        """
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.t = t
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.cancelled = False
        self.start()

    async def cb(self):
        await self.callback(*self.args, **self.kwargs)

    def run(self):
        asyncio.sleep(self.t)
        if not self.cancelled:
            self.loop.run_until_complete(self.cb())

    def cancel(self):
        self.cancelled = True


async def write_debug_channel(bot: Bot, message):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(message)


async def write_debug_channel_embed(bot: Bot, embed):
    """Writes the given message to the bot's debug channel"""
    debug_chan = bot.get_channel(Config().DEBUG_CHAN_ID)
    if debug_chan is not None:
        await debug_chan.send(embed=embed)


def get_best_username(user):
    """
    :param user: User that is to be identified
    :return: Returns the best fit for a human-readable identifier ("username") of user.
    """
    if user.nick is None:
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
