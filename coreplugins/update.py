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
from data import Config, Lang
from botutils import restclient, utils, permchecks
from botutils.stringutils import paginate
from botutils.utils import sort_commands_helper, add_reaction
from subsystems.helpsys import DefaultCategories
from subsystems.presence import PresencePriority

# Assumed version numbering system:
# 2.3.1
# 2.5-a

# CONFIG

log = logging.getLogger(__name__)
CONFIRMTIMEOUT = 10
OWNER = "gobo7793"
REPO = "Geckarbot"

# Github API things
URL = "https://api.github.com"
ENDPOINT = "repos/{}/{}/releases".format(OWNER, REPO)

# these values are coordinated with runscript.sh
TAGFILE = ".update"
ERRORCODE = "FAILURE"


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
    """Checks if the both version strings are the same version"""
    vs1 = sanitize_version_s(vstring1)
    vs2 = sanitize_version_s(vstring2)
    vs1 = vs1.split(".")
    vs2 = vs2.split(".")
    if len(vs2) > len(vs1):
        vs1, vs2 = vs2, vs1

    # fish for letters at the end
    vd1, _, vl1 = consume_digits(vs1[-1])
    vd2, _, vl2 = consume_digits(vs2[-1])
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
    vd1, _, vl1 = consume_digits(vs1[-1])
    vd2, _, vl2 = consume_digits(vs2[-1])
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
        if vs1[i] < vs2[i]:
            return False
        # ==; check for letters or compare further
        if i == len(vs1) - 1:
            if vl2:
                return not vl1
        continue

    # Completely the same it seems
    return False


class State(Enum):
    """State of the Updater"""

    IDLE = 0
    """Does nothing"""
    CHECKING = 1
    """Checking for updates"""
    WAITINGFORCONFIRM = 2
    """Waiting to confirm the update"""
    CONFIRMED = 3
    """Update is confirmed, pending to perform"""
    UPDATING = 4
    """Performs the pending update"""


class Plugin(BasePlugin, name="Bot updating system"):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.client = restclient.Client(URL)

        self.bot.loop.run_until_complete(self.was_i_updated())
        self.state = State.IDLE

        self.to_log = None
        self.waiting_for_confirm = None
        bot.register(self, category=DefaultCategories.ADMIN)

        # Add commands to help category 'user'
        to_add = ("version", "news")
        for cmd in self.get_commands():
            if cmd.name in to_add:
                self.bot.helpsys.default_category(DefaultCategories.USER).add_command(cmd)

    def sort_commands(self, ctx, command, subcommands):
        order = [
            "version",
            "news",
            "update",
            "restart",
            "shutdown"
        ]
        return sort_commands_helper(subcommands, order)

    def get_configurable_type(self):
        return ConfigurableType.COREPLUGIN

    async def do_update(self, channel, tag):
        """
        Performs an pending update

        :param channel: The channel for the info message that a update is performed
        :param tag: The version tag to update to
        """
        # pylint: disable=broad-except
        self.state = State.UPDATING
        self.bot.presence.register(Lang.lang(self, "presence_update", tag), PresencePriority.HIGH)
        await channel.send(Lang.lang(self, "doing_update", tag))
        for plugin in self.bot.plugin_objects(plugins_only=True):
            try:
                await utils.write_debug_channel("Shutting down plugin {}".format(plugin.get_name()))
                await plugin.shutdown()
            except Exception as e:
                msg = "{} while trying to shutdown plugin {}:\n{}".format(
                    str(e), plugin.get_name(), traceback.format_exc()
                )
                await utils.write_debug_channel(msg)

        await self.bot.close()
        with open(TAGFILE, "w") as f:
            f.write(tag)
        await self.bot.shutdown(Geckarbot.Exitcodes.UPDATE)  # This signals the runscript

    async def get_releases(self):
        """Get all published releases from Github"""
        r = await self.client.request(ENDPOINT)
        return r

    async def check_release(self, version=None):
        """
        Checks GitHub if there is a new release. Assumes that the GitHub releases are ordered by release date.

        :return: Tag of the newest release that is newer than the current version, None if there is none.
        """
        # find newest release with tag (all the others are worthless anyway)
        release = None
        for el in await self.get_releases():
            if "tag_name" in el:
                el = el["tag_name"]
                if version is None and (release is None or is_newer(el, release)):
                    release = el
                elif version is not None and el == version:
                    release = el
                    break
        if release is None:
            return None

        if version is not None or is_newer(release, self.bot.VERSION):
            return release
        return None

    async def update_news(self, channel, version=None):
        """
        Sends release notes to channel.

        :param channel: Channel to send the release notes to.
        :param version: Release version that the news should be about.
        """
        if version == "latest":
            version = await self.check_release()
        if version is None:
            version = self.bot.VERSION
        ver = None
        body = None
        for el in await self.get_releases():
            ver = sanitize_version_s(el["tag_name"])
            log.debug("Comparing versions: %s and %s", self.bot.VERSION, ver)
            if is_equal(sanitize_version_s(version), ver):
                body = el["body"]
                break

        if body is None:
            await channel.send(Lang.lang(self, "err_no_news_for_version", version))
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
            log.debug("I was not !update'd.")
            return False
        except IsADirectoryError:
            log.error("%s is a directory, I expected a file or nothing. Please clean this up.", TAGFILE)
            return False

        lines = f.readlines()
        if len(lines) > 1:
            log.error("%s has more than 1 line. This should not happen.", TAGFILE)
            return False
        if len(lines) == 0 or lines[0].strip() == "":
            log.error("%s is empty. This should not happen.", TAGFILE)
            return False

        if lines[0].strip() == ERRORCODE:
            await utils.write_debug_channel("The update failed. I have no idea why. Sorry, master!")
            os.remove(TAGFILE)
            return False

        log.debug("I was !update'd! Yay!")
        await utils.write_debug_channel(
            "I updated successfully! One step closer towards world dominance!")
        os.remove(TAGFILE)
        return True

    @commands.command(name="news", help="Presents the latest update notes.")
    async def cmd_news(self, ctx, *args):
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
    async def cmd_version(self, ctx):
        """Returns the version"""
        await ctx.send(Lang.lang(self, "version", self.bot.VERSION))

    @commands.command(name="restart", help="Restarts the bot.")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_restart(self, ctx):
        self.bot.presence.register(Lang.lang(self, "presence_restart"), PresencePriority.HIGH)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await self.bot.shutdown(Geckarbot.Exitcodes.RESTART)  # This signals the runscript

    @commands.command(name="shutdown", help="Stops the bot.")
    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def cmd_shutdowncmd(self, ctx):
        self.bot.presence.register(Lang.lang(self, "presence_shutdown"), PresencePriority.HIGH)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await self.bot.shutdown(Geckarbot.Exitcodes.SUCCESS)  # This signals the runscript

    @commands.command(name="replace", help="Confirms an !update command.")
    async def cmd_confirm(self, ctx):
        # Check if there is an update request running
        if self.waiting_for_confirm is None:
            return

        # Check if chan and user is the same
        chancond = self.waiting_for_confirm.channel == ctx.message.channel
        usercond = self.waiting_for_confirm.author == ctx.message.author
        if not (chancond and usercond):
            return

        await utils.log_to_admin_channel(self.to_log)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        self.to_log = None
        self.state = State.CONFIRMED

    @commands.command(name="update", help="Updates the bot if an update is available",
                      description="Updates the Bot to the newest version (if available)."
                                  " This includes a shutdown, so be careful.")
    async def cmd_update(self, ctx, version=None):
        # Argument parsing
        if not permchecks.check_admin_access(ctx.author):
            release = await self.check_release(version=version)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            if release is None:
                await ctx.message.channel.send(Lang.lang(self, "no_new_version"))
            else:
                await ctx.message.channel.send(Lang.lang(self, "new_version", release))
            return

        # Check state and send error messages if necessary
        if self.state == State.CHECKING or self.state == State.CONFIRMED or self.state == State.UPDATING:
            await ctx.message.channel.send(Lang.lang(self, "err_already_updating"))
            return
        if self.state == State.WAITINGFORCONFIRM:
            if not self.waiting_for_confirm.channel == ctx.message.channel:
                await ctx.message.channel.send(Lang.lang(self, "err_different_channel"))
            elif not self.waiting_for_confirm.author == ctx.message.author:
                await ctx.message.channel.send(Lang.lang(self, "err_different_user"))
            return
        assert self.state == State.IDLE

        # Check for new version
        self.state = State.CHECKING
        release = await self.check_release(version=version)
        if release is None:
            if version is not None:
                msg = Lang.lang(self, "version_not_found", version)
            else:
                msg = Lang.lang(self, "wont_update")
            await ctx.message.channel.send(msg)
            self.state = State.IDLE
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.message.channel.send(Lang.lang(self, "new_version_update", release))

        # Ask for confirmation
        self.state = State.WAITINGFORCONFIRM
        self.waiting_for_confirm = ctx.message
        self.to_log = ctx
        await asyncio.sleep(CONFIRMTIMEOUT)  # This means that the bot doesn't react immediately on confirmation

        # No confirmation, cancel
        if self.state == State.WAITINGFORCONFIRM:
            self.state = State.IDLE
            await ctx.message.channel.send(Lang.lang(self, "update_timeout"))
            return

        # Confirmation came in
        if self.state == State.CONFIRMED:
            await self.do_update(ctx.message.channel, release)
            return

        log.error("%s: PANIC! I am on %s, this should not happen!", self.get_name(), self.state)
        self.state = State.IDLE
        self.waiting_for_confirm = None
