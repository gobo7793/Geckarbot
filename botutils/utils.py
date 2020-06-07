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
