import string
import logging
import traceback
import os
import asyncio
import re
from enum import Enum

from discord.ext import commands

import Geckarbot
from base import BasePlugin, ConfigurableType
from botutils import restclient, utils, permchecks
from botutils.stringutils import paginate
from conf import Config, Lang
from subsystems import help

# Assumed version numbering system:
# 2.3.1
# 2.5-a

# CONFIG
CONFIRMTIMEOUT = 10
OWNER = "gobo7793"
REPO = "Geckarbot"

# Github API things
URL = "https://api.github.com"
ENDPOINT = "repos/{}/{}/releases".format(OWNER, REPO)

# these values are coordinated with runscript.sh
TAGFILE = ".update"
ERRORCODE = "FAILURE"

lang = {
    "version": "I am Geckarbot {}.",
    "no_new_version": "There is no new version. I seem to be up to date!",
    "new_version": "There is a new version that I could update to: {}! Am I going to be dispensed of now?",
    "new_version_update": "A new version is available: {}! Please don't !replace me :cry:",
    "wont_update": "There is no new version to update to.",
    "killing_plugins": "I will now ask every plugin nicely to shut down without any protest.",
    "doing_update": "These are my last words. I will update to {} now. Please don't forget me!",
    "update_timeout": "Update request cancelled. Phew, that was close!",

    "err_within_timeout": "Dude, you already requested an update.",
    "err_different_channel": "Sorry, there is already an update request running in a different channel.",
    "err_already_updating": "There is already an update in progress. Be patient.",
    "err_different_user": "Sorry, someone else already requested an update.",
    "err_no_news_for_version": "Sorry, I couldn't find any news for version {}.",
}


def sanitize_version_s(s):
    """
    Removes leading "version", "v" etc; returns a stripped, lowercased version string.
    :param s: version string to be sanitized
    :return: sanitized version string
    """
    s = s.lower()
    if s.startswith("version"):
        s = s[len("version"):]
    if s.startswith("v"):
        s = s[1:]

    return s.strip()


def consume_digits(s):
    """
    Splits arg in 3 parts. The first part is the longest substring beginning at the start that has digits, the second
    part is everything that is not a letter, the third part is the rest. Everything is converted to lowercase. Examples:
    "123abc" -> ("123", "", "abc")
    "123-Abc4" -> ("123", "-", "abc4")
    "-123" -> ("", "-", "123")
    "abc4" -> ("", "", "abc4")
    "123" -> ("123", "", "")
    :param s: string to be split
    :return: (digitsubstring, nonlettersubstring, rest)
    """
    s = s.lower()
    digits = None
    nondigits = None
    for i in range(len(s)):
        if s[i] not in string.digits:
            digits = s[:i]
            nondigits = s[i:]
            break

    if digits is None:
        digits = s[0:]
        nondigits = s[:0]

    nonletters = None
    letters = None
    for i in range(len(nondigits)):
        if nondigits[i] in string.ascii_lowercase or nondigits[i] in string.digits:
            nonletters = nondigits[:i]
            letters = nondigits[i:]
            break

    if nonletters is None:
        nonletters = nondigits[0:]
        letters = nondigits[:0]
    return digits, nonletters, letters


def is_equal(vstring1, vstring2):
    vs1 = sanitize_version_s(vstring1)
    vs2 = sanitize_version_s(vstring2)
    vs1 = vs1.split(".")
    vs2 = vs2.split(".")
    if len(vs2) > len(vs1):
        swap = vs1
        vs1 = vs2
        vs2 = swap

    # fish for letters at the end
    vd1, vnl1, vl1 = consume_digits(vs1[-1])
    vd2, vnl2, vl2 = consume_digits(vs2[-1])
    if vl1 != vl2:
        return False
    if len(vl1) > 1 or len(vl2) > 1:
        return False

    # Convert to integers
    vs1[-1] = vd1
    vs2[-1] = vd2
    for i in range(len(vs1)):
        try:
            vs1[i] = int(vs1[i])
        except ValueError:
            pass
    for i in range(len(vs2)):
        try:
            vs2[i] = int(vs2[i])
        except ValueError:
            pass

    for i in range(len(vs1)):
        # 1.2.x vs 1.2
        if i >= len(vs2):
            # 1.2.0 == 1.2
            if vs1[i] == 0:
                return True
            return False

        if vs1[i] != vs2[i]:
            return False
    return True


def is_newer(vstring1, vstring2):
    """
    Compares 2 version strings. Assumes sanitized version strings as of sanitize_version_s(). Examples:
    1.2.1 is newer than 1.2.0
    1.1.0 is newer than 1.1.0a
    1.1.0 is not newer than 1.1
    1.1.0 is not newer than 1.1.0
    1.1.0a vs. 1.1.0 is undecidable
    1.1.0a vs 1.1.0b is undecidable (cba)
    1.1.0ab vs 1.1.0a is undecidable
    1.1.a is undecidable
    1.1a.0 is undecidable
    Anything non-ascii is undecidable
    There is no difference between 1.1.0-a and 1.1.0a
    :return: True if vstring is newer than vstrin2, False if not (especially if it is undecidable).
    """
    vs1 = vstring1.lower()
    vs2 = vstring2.lower()

    vs1 = vs1.split(".")
    vs2 = vs2.split(".")

    # fish for letters at the end
    vd1, vnl1, vl1 = consume_digits(vs1[-1])
    vd2, vnl2, vl2 = consume_digits(vs2[-1])
    if len(vl1) > 1 or len(vl2) > 1:
        return False

    # Convert to integers
    vs1[-1] = vd1
    vs2[-1] = vd2
    for i in range(len(vs1)):
        try:
            vs1[i] = int(vs1[i])
        except ValueError:  # should only happen on "", therefore undecidable
            vs1[i] = None
    for i in range(len(vs2)):
        try:
            vs2[i] = int(vs2[i])
        except ValueError:  # should only happen on "", therefore undecidable (checked further down)
            vs2[i] = None

    for i in range(len(vs1)):
        # 1.2.x vs 1.2
        if i >= len(vs2):
            # 1.2.0 == 1.2
            if vs1[i] == 0:
                return False
            return True

        if vs2[i] is None or vs1[i] is None:
            return False

        if vs1[i] > vs2[i]:
            return True
        elif vs1[i] < vs2[i]:
            return False
        # ==; check for letters or compare further
        elif i == len(vs1) - 1:
            if vl2:
                if not vl1:
                    return True
                else:
                    return False
        else:
            continue

    # Completely the same it seems
    return False


def testthesethings():
    assert consume_digits("123abc") == ("123", "", "abc")
    assert consume_digits("123-Abc4") == ("123", "-", "abc4")
    assert consume_digits("-123") == ("", "-", "123")
    assert consume_digits("abc4") == ("", "", "abc4")
    assert consume_digits("123") == ("123", "", "")

    assert is_newer("1.2.1", "1.2.0")
    assert is_newer("1.1.0", "1.1.0a")
    assert is_newer("1.2.a", "1.1.0")
    assert not is_newer("1.1.0", "1.1")
    assert not is_newer("1.1.0", "1.1.0")
    assert not is_newer("1.1.0a", "1.1.0")
    assert not is_newer("1.1.0a", "1.1.0b")
    assert not is_newer("1.1.0ab", "1.1.0a")
    assert not is_newer("1.1.a", "1.1.0")
    assert not is_newer("1.1a.0", "1.1.0")

    assert is_equal("1.2.3", "1.2.3")
    assert is_equal("1.2.0", "1.2")
    assert is_equal("1.2", "1.2.0")
    assert is_equal("1.1-a", "1.1a")
    assert is_equal("1.a", "1.a")
    assert is_equal("foo", "foo")
    assert not is_equal("1.1.0", "1.2.0")
    assert not is_equal("1.1.0", "1.1.1")
    assert not is_equal("1.1.1-a", "1.1.1")


class State(Enum):
    IDLE = 0
    CHECKING = 1
    WAITINGFORCONFIRM = 2
    CONFIRMED = 3
    UPDATING = 4


class Plugin(BasePlugin, name="Bot updating system"):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.client = restclient.Client(URL)

        self.bot.loop.run_until_complete(self.was_i_updated())
        self.state = State.IDLE

        self.to_log = None
        self.waiting_for_confirm = None
        bot.register(self, category=help.DefaultCategories.ADMIN)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    async def do_update(self, channel, tag):
        self.state = State.UPDATING
        await channel.send(lang["doing_update"].format(tag))
        for plugin in self.bot.plugin_objects(plugins_only=True):
            try:
                await utils.write_debug_channel(self.bot, "Shutting down plugin {}".format(plugin.get_name()))
                await plugin.shutdown()
            except Exception as e:
                msg = "{} while trying to shutdown plugin {}:\n{}".format(
                    str(e), plugin.get_name(), traceback.format_exc()
                )
                await utils.write_debug_channel(self.bot, msg)

        await self.bot.close()
        with open(TAGFILE, "w") as f:
            f.write(tag)
        await self.bot.shutdown(Geckarbot.Exitcodes.UPDATE)  # This signals the runscript

    def get_releases(self):
        r = self.client.make_request(ENDPOINT)
        return r

    def check_release(self):
        """
        Checks GitHub if there is a new release. Assumes that the GitHub releases are ordered by release date.
        :return: Tag of the newest release that is newer than the current version, None if there is none.
        """
        # return "1.3"  # TESTING
        # find newest release with tag (all the others are worthless anyway)
        release = None
        for el in self.get_releases():
            if "tag_name" in el:
                el = el["tag_name"]
                if release is None or is_newer(el, release):
                    release = el
        if release is None:
            return None

        if is_newer(release, Config().VERSION):
            return release
        return None

    async def update_news(self, channel, version=None):
        """
        Sends release notes to channel.
        :param channel: Channel to send the release notes to.
        :param version: Release version that the news should be about.
        """
        if version is None:
            version = Config().VERSION
        ver = None
        body = None
        for el in self.get_releases():
            ver = sanitize_version_s(el["tag_name"])
            logging.getLogger(__name__).debug("Comparing versions: {} and {}".format(Config().VERSION, ver))
            if is_equal(sanitize_version_s(version), ver):
                body = el["body"]
                break

        if body is None:
            await channel.send(lang["err_no_news_for_version"].format(version))
            return

        # Make headlines great again!
        lines = []
        p = re.compile(r"\s*#+\s*(.*)")
        for el in body.split("\n"):
            m = p.match(el)
            if m:
                el = "**{}**".format(m.groups()[0])
            lines.append(el)

        for page in paginate(lines, prefix="**Version {}:**\n".format(ver), msg_prefix="_ _\n", delimiter=""):
            await channel.send(page)

    async def was_i_updated(self):
        """
        Checks if there was an !update before the bot launch. Does cleanup and message sending.
        Does not delete TAGFILE if it had unexpected content.
        :return: True if there was a successful update, False if not
        """
        try:
            f = open(TAGFILE)
        except FileNotFoundError:
            logging.getLogger(__name__).debug("I was not !update'd.")
            return False
        except IsADirectoryError:
            logging.getLogger(__name__).error(
                "{} is a directory, I expected a file or nothing. Please clean this up.".format(TAGFILE))
            return False

        lines = f.readlines()
        if len(lines) > 1:
            logging.getLogger(__name__).error("{} has more than 1 line. This should not happen.".format(TAGFILE))
            return False
        if len(lines) == 0 or lines[0].strip() == "":
            logging.getLogger(__name__).error("{} is empty. This should not happen.".format(TAGFILE))
            return False

        if lines[0].strip() == ERRORCODE:
            await utils.write_debug_channel(self.bot, "The update failed. I have no idea why. Sorry, master!")
            os.remove(TAGFILE)
            return False
        else:
            logging.getLogger(__name__).debug("I was !update'd! Yay!.")
            await utils.write_debug_channel(
                self.bot, "I updated successfully! One step closer towards world dominance!")
            os.remove(TAGFILE)
            return True

    @commands.command(name="news", help="Presents the latest update notes.")
    async def news(self, ctx, *args):
        version = None
        if len(args) == 0:
            pass
        elif len(args) == 1:
            version = args[0]
        else:
            await ctx.message.channel.send("Too many arguments.")
            return

        await self.update_news(ctx.message.channel, version=version)

    @commands.command(name="version", help="Returns the running bot version.")
    async def version(self, ctx):
        """Returns the version"""
        await ctx.send(lang["version"].format(Config().VERSION))

    @commands.command(name="restart", help="Restarts the bot.")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def restart(self, ctx):
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        await self.bot.shutdown(Geckarbot.Exitcodes.RESTART)  # This signals the runscript

    @commands.command(name="shutdown", help="Stops the bot.")
    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def shutdowncmd(self, ctx):
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        await self.bot.shutdown(Geckarbot.Exitcodes.SUCCESS)  # This signals the runscript

    @commands.command(name="replace", help="Confirms an !update command.")
    async def confirm(self, ctx):
        # Check if there is an update request running
        if self.waiting_for_confirm is None:
            return

        # Check if chan and user is the same
        chancond = self.waiting_for_confirm.channel == ctx.message.channel
        usercond = self.waiting_for_confirm.author == ctx.message.author
        if not (chancond and usercond):
            return

        await utils.log_to_admin_channel(self.to_log)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        self.to_log = None
        self.state = State.CONFIRMED

    @commands.command(name="update", help="Updates the bot if an update is available",
                      description="Updates the Bot to the newest version (if available)."
                                  " This includes a shutdown, so be careful.")
    async def update(self, ctx, check=None):
        # Argument parsing
        if not permchecks.check_full_access(ctx.author) or check == "check":
            release = self.check_release()
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            if release is None:
                await ctx.message.channel.send(lang["no_new_version"])
            else:
                await ctx.message.channel.send(lang["new_version"].format(release))
            return

        # Check state and send error messages if necessary
        if self.state == State.CHECKING or self.state == State.CONFIRMED or self.state == State.UPDATING:
            await ctx.message.channel.send(lang["err_already_updating"])
            return
        if self.state == State.WAITINGFORCONFIRM:
            if not self.waiting_for_confirm.channel == ctx.message.channel:
                await ctx.message.channel.send(lang["err_different_channel"])
            elif not self.waiting_for_confirm.author == ctx.message.author:
                await ctx.message.channel.send(lang["err_different_user"])
            return
        assert self.state == State.IDLE

        # Check for new version
        self.state = State.CHECKING
        release = self.check_release()
        if release is None:
            await ctx.message.channel.send(lang["wont_update"])
            self.state = State.IDLE
            return
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        await ctx.message.channel.send(lang["new_version_update"].format(release))

        # Ask for confirmation
        self.state = State.WAITINGFORCONFIRM
        self.waiting_for_confirm = ctx.message
        self.to_log = ctx
        await asyncio.sleep(CONFIRMTIMEOUT)  # This means that the bot doesn't react immediately on confirmation

        # No confirmation, cancel
        if self.state == State.WAITINGFORCONFIRM:
            self.state = State.IDLE
            await ctx.message.channel.send(lang["update_timeout"])
            return

        # Confirmation came in
        elif self.state == State.CONFIRMED:
            await self.do_update(ctx.message.channel, release)
            return
        else:
            logging.getLogger(__name__).error(
                "{}: PANIC! I am on {}, this should not happen!".format(self.get_name(), self.state))
            self.state = State.IDLE
            self.waiting_for_confirm = None
