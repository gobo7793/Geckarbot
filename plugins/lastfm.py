import logging
from enum import Enum
from datetime import datetime
from typing import Union
import time
import random
import re
import pprint
from urllib.error import HTTPError

import discord
from discord.ext import commands

from base import BasePlugin, NotLoadable
from data import Config, Lang, Storage
from botutils.converters import get_best_username as gbu, get_best_user
from botutils.timeutils import hr_roughly
from botutils.stringutils import paginate
from botutils.utils import write_debug_channel, add_reaction, helpstring_helper
from botutils.questionnaire import Questionnaire, Question, QuestionType, Cancelled
from botutils.restclient import Client
from botutils.setter import ConfigSetter


BASEURL = "https://ws.audioscrobbler.com/2.0/"
mention_p = re.compile(r"<@[^>]+>")


class NotRegistered(Exception):
    """
    Raised when information is requested that concerns a user that has not registered his Last.fm name.
    """
    def __init__(self, plugin):
        self.plugin = plugin
        super().__init__()

    async def default(self, ctx, sg3p=False):
        if sg3p:
            msg = "not_registered_sg3p"
        else:
            msg = "not_registered"
        await add_reaction(ctx.message, Lang.CMDERROR)
        await ctx.send(Lang.lang(self.plugin, msg))


class UnexpectedResponse(Exception):
    """
    Returned when last.fm returns an unexpected response.
    """
    def __init__(self, msg, usermsg):
        self.user_message = usermsg
        super().__init__(msg)

    async def default(self, ctx):
        await add_reaction(ctx.message, Lang.CMDERROR)
        await ctx.send(self.user_message)


class MostInterestingType(Enum):
    TITLE = 0
    ALBUM = 1
    ARTIST = 2


class Song:
    """
    Represents an occurence of a title in a scrobble history, i.e. a scrobble.
    """
    def __init__(self, plugin, artist, album, title, nowplaying=False, timestamp=None, loved=False):
        self.plugin = plugin
        self.artist = artist
        self.album = album
        self.title = title
        self.nowplaying = nowplaying
        self.timestamp = timestamp
        self.loved = loved

    @classmethod
    def from_response(cls, plugin, element):
        """
        Builds a song from a dict as returned by last.fm API.

        :param plugin: reference to Plugin
        :param element: part of a response that represents a song
        :return: Song object that represents `element`
        :raises KeyError: Necessary information is missing in `element`
        """
        plugin.logger.debug("Building song from {}".format(pprint.pformat(element)))
        title = element["name"]
        album = element["album"]["#text"]

        # Artist
        artist = element["artist"]
        if "name" in artist:
            artist = artist["name"]
        elif "#text" in artist:
            artist = artist["#text"]
        else:
            raise KeyError("\"name\" or \"#text\" in artist")

        # Now playing
        nowplaying = element.get("@attr", {}).get("nowplaying", "false")
        if nowplaying == "true":
            nowplaying = True
        else:
            if nowplaying != "false":
                write_debug_channel("WARNING: lastfm: unexpected \"nowplaying\": {}".format(nowplaying))
            nowplaying = False

        # Loved
        loved = element.get("loved", "0")
        if loved == "1":
            loved = True
        else:
            if loved != "0":
                write_debug_channel("Lastfm: Unknown \"loved\" value: {}".format(loved))
            loved = False

        # Timestamp
        ts = element.get("date", {}).get("uts", "0")
        try:
            ts = datetime.fromtimestamp(int(ts))
        except (TypeError, ValueError):
            ts = None

        return cls(plugin, artist, album, title, nowplaying=nowplaying, timestamp=ts, loved=loved)

    def quote(self, p: float = None):
        """
        Returns a random quote if there is one.

        :param p: Probability (defaults to config value quote_p)
        :return: quote
        """
        if p is None:
            p = self.plugin.get_config("quote_p")

        quotes = self.plugin.get_quotes(self.artist, self.title)
        if quotes:
            qkey = random.choice(list(quotes.keys()))
            if p is not None and random.choices([True, False], weights=[p, 1 - p])[0]:
                return quotes[qkey]["quote"]
        return None

    def format_song(self):
        """
        :return: Nice readable representation of the song according to lang string
        """
        r = Lang.lang(self.plugin, "listening_song_base", self.title, self.artist)
        if self.loved:
            r = "{} {}".format(Lang.lang(self.plugin, "loved"), r)
        return r

    def __getitem__(self, key):
        if key == "artist":
            return self.artist
        if key == "album":
            return self.album
        if key == "title":
            return self.title
        if key == "nowplaying":
            return self.nowplaying
        if key == "loved":
            return self.loved
        raise KeyError

    def __repr__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)

    def __str__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)


class Plugin(BasePlugin, name="LastFM"):
    def __init__(self, bot):
        super().__init__(bot)

        self.logger = logging.getLogger(__name__)
        self.migrate()
        self.client = Client(BASEURL)
        self.conf = Config.get(self)
        if not self.conf.get("apikey", ""):
            raise NotLoadable("API Key not found")
        self.dump_except_keys = ["username", "password", "apikey", "sharedsecret"]

        bot.register(self, category_desc=Lang.lang(self, "cat_desc"))

        self.perf_total_time = None
        self.perf_lastfm_time = None
        self.perf_request_count = 0
        self.perf_reset_timers()

        # Config setter
        self.base_config = {
            "limit": [int, 5],
            "min_artist": [float, 0.5],
            "min_album": [float, 0.4],
            "min_title": [float, 0.5],
            "mi_downgrade": [float, 1.5],
            "quote_p": [float, 0.5],
            "max_quote_length": [int, 100],
        }
        self.config_setter = ConfigSetter(self, self.base_config)

        # Quote lang dicts
        self.lang_question = {
            "or": Lang.lang(self, "or"),
            "answer_cancel": Lang.lang(self, "quote_cancel"),
            "answer_list_sc": "",
        }
        self.lang_questionnaire = {
            "intro": "",
            "intro_howto_cancel": "",
            "result_rejected": Lang.lang(self, "quote_invalid"),
            "state_cancelled": Lang.lang(self, "quote_cancelled"),
            "state_done": "",
            "answer_list_sc": Lang.lang(self, "quote_answer_list_sc"),
        }
        self.cmd_order = [
            "now",
            "register",
            "deregister",
            "profile",
            "quote",
        ]

    def migrate(self):
        """
        Migrate quotes from version 1 to version 2
        """
        struc = Storage.get(self, container="quotes")
        if struc["version"] == 1:
            quoteslist = struc.get("quotes", [])
            new_quoteslist = {}
            for i in range(len(quoteslist)):
                artist, title, quotes = quoteslist[i]
                new_quotes = {}
                for j in range(len(quotes)):
                    new_quotes[j+1] = {
                        "author": None,
                        "quote": quotes[j],
                    }
                new_quoteslist[i+1] = {
                    "artist": artist,
                    "title": title,
                    "quotes": new_quotes,
                }
            struc["quotes"] = new_quoteslist
            struc["version"] = 2
            Storage.save(self, container="quotes")

    def get_config(self, key):
        return Config.get(self).get(key, self.base_config[key][1])

    def default_config(self):
        return {}

    def default_storage(self, container=None):
        if container is None:
            return {
                "users": {}
            }
        if container == "quotes":
            return {
                "version": 2,
                "quotes": {}
            }
        raise RuntimeError("unknown storage container {}".format(container))

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def sort_commands(self, ctx, command, subcommands):
        if command is None:
            return subcommands

        if command.name != "lastfm":
            return super().sort_commands(ctx, command, subcommands)
        r = []
        for el in self.cmd_order:
            for cmd in subcommands:
                if cmd.name == el:
                    r.append(cmd)
        return r

    async def request(self, params, method="GET"):
        """
        Does a request to last.fm API and parses the reponse to a dict.

        :param params: URL parameters
        :param method: HTTP method
        :return: Response dict
        """
        params["format"] = "json"
        params["api_key"] = self.conf["apikey"]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Geckarbot/{}".format(self.bot.VERSION)
        }
        before = self.perf_timenow()
        r = await self.client.request("", params=params, headers=headers, method=method)
        after = self.perf_timenow()
        self.perf_add_lastfm_time(after - before)
        return r

    def get_lastfm_user(self, user: discord.User):
        """
        :param user: discord user
        :return: Corresponding last.fm user
        :raises NotRegistered: `user` did not register their last.fm username
        """
        r = Storage.get(self)["users"].get(user.id, None)
        if r is None:
            raise NotRegistered(self)
        return r

    def perf_reset_timers(self):
        """
        Resets the performance timers.
        """
        self.perf_lastfm_time = 0.0
        self.perf_total_time = 0.0
        self.perf_request_count = 0

    def perf_add_lastfm_time(self, t: float):
        """
        Adds time that was spent waiting for last.fm API for performance measuring.

        :param t: time to add
        """
        self.perf_lastfm_time += t

    def perf_add_total_time(self, t: float):
        """
        Adds time that was spent executing things for performance measuring.

        :param t: time to add
        """
        self.perf_total_time += t
        self.perf_request_count += 1

    def get_quotes(self, artist, title):
        """
        Fetches the quotes for an artist-title-pair.

        :param artist: Artist
        :param title: Title
        :return: Returns a dict of the form {int i: {"author": userid, "quote": quotestring}}
        """
        quotes = Storage.get(self, container="quotes").get("quotes", [])
        for el in quotes.keys():
            if quotes[el]["artist"].lower() == artist.lower() and quotes[el]["title"].lower() == title.lower():
                return quotes[el]["quotes"]
        return {}

    @staticmethod
    def perf_timenow():
        return time.clock_gettime(time.CLOCK_MONOTONIC)

    @commands.group(name="lastfm", invoke_without_command=True)
    async def cmd_lastfm(self, ctx):
        self.perf_reset_timers()
        before = self.perf_timenow()
        try:
            async with ctx.typing():
                await self.most_interesting(ctx, ctx.author)
        except (NotRegistered, UnexpectedResponse) as e:
            await e.default(ctx)
            return
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    @commands.has_role(Config().BOT_ADMIN_ROLE_ID)
    @cmd_lastfm.command(name="config", aliases=["set"], hidden=True)
    async def cmd_config(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        await self.config_setter.set_cmd(ctx, key, value)

    @cmd_lastfm.command(name="register")
    async def cmd_register(self, ctx, lfmuser: str):
        info = await self.get_user_info(lfmuser)
        if info is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "user_not_found", lfmuser))
            return
        if "user" not in info:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(self, "error")
            await write_debug_channel("Error: \"user\" not in {}".format(info))
            return
        Storage.get(self)["users"][ctx.author.id] = lfmuser
        Storage.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_lastfm.command(name="deregister")
    async def cmd_deregister(self, ctx):
        if ctx.author.id in Storage.get(self)["users"]:
            del Storage.get(self)["users"][ctx.author.id]
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    @cmd_lastfm.command(name="profile", usage="<User>")
    async def cmd_profile(self, ctx, user: Union[discord.Member, discord.User, None]):
        sg3p = False
        if user is None:
            sg3p = True
            user = ctx.author

        try:
            user = self.get_lastfm_user(user)
        except NotRegistered as e:
            await e.default(ctx, sg3p=sg3p)
            return
        await ctx.send("http://last.fm/user/{}".format(user))

    @cmd_lastfm.command(name="performance", hidden=True)
    async def cmd_perf(self, ctx):
        decdigits = 3
        total = round(self.perf_total_time, decdigits)
        lastfm = round(self.perf_lastfm_time, decdigits)
        percent = int(round(lastfm * 100 / total))
        await ctx.send(Lang.lang(self, "performance", lastfm, total, percent, self.perf_request_count))

    @cmd_lastfm.command(name="page", aliases=["history"], hidden=True)
    async def cmd_history(self, ctx, page: int = 1):
        self.perf_reset_timers()
        before = self.perf_timenow()
        pagelen = 10
        try:
            lfmuser = self.get_lastfm_user(ctx.author)
        except NotRegistered as e:
            await e.default(ctx)
            return
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "page": page,
            "limit": pagelen
        }
        try:
            songs = self.build_songs(await self.request(params))
        except UnexpectedResponse as e:
            await e.default(ctx)
            return

        for i in range(len(songs)):
            songs[i] = self.listening_msg(ctx.author, songs[i])
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        for msg in paginate(songs):
            await ctx.send(msg)
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    async def quote_dm_kill_cb(self, msg, questionnaire):
        """
        Callback for when the DM registration is killed

        :param msg: message string
        :param questionnaire: Questionnare object
        """
        await questionnaire.user.send(Lang.lang(self, "quote_err_dmkill"))
        await add_reaction(msg, Lang.CMDERROR)

    async def quote_so_far_helper(self, user, song):
        """
        Sends a list of current quotes to User `user`'s DM

        :param user: User
        :param song: Song instance
        """
        self.logger.debug("Sending current quotes for %s to %s", str(song), str(user))
        msg = [Lang.lang(self, "quote_existing_quotes")]
        quotes = self.get_quotes(song.artist, song.title)
        for key in quotes:
            author = get_best_user(quotes[key]["author"])
            author = gbu(author) if author is not None else Lang.lang(self, "quote_unknown_user")
            msg.append(Lang.lang(self, "quote_list_entry", quotes[key]["quote"], author))
        if len(msg) == 1:
            return

        for msg in paginate(msg):
            await user.send(msg)

    async def quote_scrobble_cb(self, question, question_queue):
        """
        Is called when the answer for the question "scrobble or new?" comes in

        :param question: Question object
        :param question_queue: list of Question objects that were to be posed after this
        :return: question_queue
        """
        if question.answer == question.data["new"]:
            self.logger.debug("Got answer new")
            question.data["result_scrobble"] = False
            return [question.data["q_artist"], question.data["q_title"]]
        elif question.answer == question.data["scrobble"]:
            self.logger.debug("Got answer scrobble")
            question.data["result_scrobble"] = True
            return question_queue
        else:
            assert False

    async def quote_new_song_cb(self, question, question_queue):
        """
        Is called when the answer for the question "Title?" comes in

        :param question: Question object
        :param question_queue: list of Question objects that were to be posed after this
        :return: question_queue
        """
        print("question: {}, queue: {}".format(question, question_queue))
        song = Song(self, question.data["q_artist"].answer, "", question.data["q_title"].answer)
        question.data["song"] = song
        question.data["result_scrobble"] = False
        await self.quote_so_far_helper(question.data["user"], song)
        return question_queue

    async def quote_acquire_song(self, ctx, user, question_lang_key) -> Song:
        # Fetch scrobbled song
        lfmuser = self.get_lastfm_user(user)

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
            "extended": 1,
        }
        response = await self.request(params)
        song = self.build_songs(response)[0]

        # Build questionnaire
        q_artist = Question(Lang.lang(self, "quote_question_artist"), QuestionType.TEXT, lang=self.lang_question)
        q_title = Question(Lang.lang(self, "quote_question_title"), QuestionType.TEXT, lang=self.lang_question,
                           callback=self.quote_new_song_cb)
        cargo = {
            "user": ctx.author,
            "song": song,
            "q_artist": q_artist,
            "q_title": q_title,
            "scrobble": Lang.lang(self, "quote_scrobble"),
            "new": Lang.lang(self, "quote_new"),
            "result_scrobble": True,
            "result_artist": None,
            "result_title": None,
        }
        q_title.data = cargo
        answers = [Lang.lang(self, "quote_scrobble"), Lang.lang(self, "quote_new")]
        q_target = Question(Lang.lang(self, question_lang_key, song.format_song()), QuestionType.SINGLECHOICE,
                            answers=answers, data=cargo, lang=self.lang_question, callback=self.quote_scrobble_cb)
        questions = [q_target]
        questionnaire = Questionnaire(self.bot, ctx.author, questions, "lastfm quote", lang=self.lang_questionnaire)

        # Interrogate
        await questionnaire.interrogate()
        return cargo["song"]

    async def quote_sanity_cb(self, question, question_queue):
        """
        Callback for quote sanity check

        :param question: Question object
        :param question_queue: list of question objects
        :return: new question queue
        """
        p = mention_p.search(question.answer)
        if p:
            await add_reaction(question.answer_msg, Lang.CMDERROR)
            await question.answer_msg.channel.send(Lang.lang(self, "quote_err_no_mentions"))
            return [question] + question_queue

        maxlen = self.get_config("max_quote_length")
        if len(question.answer) > maxlen:
            await add_reaction(question.answer_msg, Lang.CMDERROR)
            await question.answer_msg.channel.send(Lang.lang(self, "quote_err_length", maxlen, len(question.answer)))
            return [question] + question_queue
        return question_queue

    @cmd_lastfm.group(name="quote", invoke_without_command=True)
    async def cmd_quote(self, ctx):
        # Questionnaires
        try:
            song = await self.quote_acquire_song(ctx, ctx.author, "quote_target")
        except Cancelled:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return
        except (NotRegistered, UnexpectedResponse) as e:
            await e.default(ctx)
            return

        q_quote = Question(Lang.lang(self, "quote_question_quote"), QuestionType.TEXT,
                           lang=self.lang_question, callback=self.quote_sanity_cb)
        questionnaire = Questionnaire(self.bot, ctx.author, [q_quote], "lastfm quote", lang=self.lang_questionnaire)
        await questionnaire.interrogate()
        await ctx.author.send(Lang.lang(self, "quote_done"))

        # Build new quote
        quotes = self.get_quotes(song.artist, song.title)
        if not quotes:
            ta = {
                "artist": song.artist,
                "title": song.title,
                "quotes": quotes,
            }
            allquotes = Storage.get(self, container="quotes")["quotes"]
            allquotes[get_new_key(allquotes)] = ta
        self.logger.debug("Adding quote: %s to %s", str(q_quote.answer), str(quotes))
        quote = {
            "author": ctx.author.id,
            "quote": q_quote.answer,
        }

        # Add quote
        quotes[get_new_key(quotes)] = quote
        Storage.save(self, container="quotes")

        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_quote.command(name="del", aliases=["rm", "remove"], hidden=True)
    async def cmd_quote_del(self, ctx):
        try:
            song = await self.quote_acquire_song(ctx, ctx.author, "quote_del_target")
        except Cancelled:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return
        except (NotRegistered, UnexpectedResponse) as e:
            await e.default(ctx)
            return
        await ctx.send("{}, {}".format(song.artist, song.title))

    @cmd_lastfm.command(name="now", aliases=["listening"])
    async def cmd_now(self, ctx, user: Union[discord.Member, discord.User, str, None]):
        self.perf_reset_timers()
        before = self.perf_timenow()
        lfmuser = user
        sg3p = False
        if user is None:
            sg3p = True
            user = ctx.author
        if isinstance(user, (discord.Member, discord.User)):
            try:
                lfmuser = self.get_lastfm_user(user)
            except NotRegistered as e:
                await e.default(ctx, sg3p=sg3p)
                return
        else:
            # user is a str
            userinfo = await self.get_user_info(user)
            if userinfo is None:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "user_not_found", user))
                return

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
            "extended": 1,
        }

        async with ctx.typing():
            response = await self.request(params)
            try:
                song = self.build_songs(response)[0]
            except UnexpectedResponse as e:
                await e.default(ctx)
                return

        await ctx.send(self.listening_msg(user, song))
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    def listening_msg(self, user, song):
        """
        Builds a "x is listening to y" message string.

        :param user: User that is listening
        :param song: song dict
        :return: Message string that is ready to be sent
        """
        if song.title.strip().lower().startswith("keine lust") and random.choice([True, True, False]):
            return "Keine Lust :("
        msg = song.format_song()
        if song["album"]:
            msg = Lang.lang(self, "listening_song_album", msg, song["album"])
        if song["nowplaying"]:
            msg = Lang.lang(self, "listening_base_present", gbu(user), msg)
        else:
            msg = Lang.lang(self, "listening_base_past", gbu(user), msg)
        quote = song.quote()
        if quote:
            msg = "{} _{}_".format(msg, quote)
        return msg

    async def get_user_info(self, lfmuser):
        """
        Fetches info about a last.fm user

        :param lfmuser: last.fm username
        :return: userinfo dict
        """
        params = {
            "method": "user.getInfo",
            "user": lfmuser
        }
        try:
            userinfo = await self.request(params)
        except HTTPError:
            return None

        if "error" in userinfo:
            return None
        return userinfo

    def build_songs(self, response, append_to=None, first=True):
        """
        Builds song dicts out of a response.

        :param response: Response from the Last.fm API
        :param append_to: Append resulting songs to this list instead of building a new one.
        :param first: If False, removes a leading "nowplaying" song if existant.
        :return: List of song dicts that have the keys `artist`, `title`, `album`, `nowplaying`
        :raises UnexpectedResponse: The last.fm response is missing necessary information
        """
        try:
            tracks = response["recenttracks"]["track"]
        except KeyError as e:
            raise UnexpectedResponse("\"recenttracks\" not in response", Lang.lang(self, "api_error")) from e
        r = [] if append_to is None else append_to
        done = False
        for el in tracks:
            song = Song.from_response(self, el)
            if not first and not done and song.nowplaying:
                done = True
                continue
            r.append(Song.from_response(self, el))
        return r

    @staticmethod
    def interest_match(song, criterion, example):
        """
        Checks whether a song is in the same mi type criterion category as another.

        :param song: Song object
        :param criterion: MostInterestingType object
        :param example:
        :return: True if `song` and `example` have matching categories according to `criterion`
        """
        if criterion == MostInterestingType.ARTIST:
            return song["artist"] == example["artist"]

        if criterion == MostInterestingType.ALBUM:
            return song["artist"] == example["artist"] and song["album"] == example["album"]

        if criterion == MostInterestingType.TITLE:
            return song["artist"] == example["artist"] and song["title"] == example["title"]

        return None

    @staticmethod
    def expand_formula(top_index, top_matches, current_index, current_matches):
        """
        Contains the decision process for expansion.

        :param top_index: Index of last song that had a positive expand result
        :param top_matches: Amount of matches of the last positive expand result
        :param current_index: Index of the current song
        :param current_matches: Amount of matches so far
        :return: `True` if expansion is to be done, `False` otherwise
        """
        return current_matches / current_index > (top_matches - 2) / top_index

    async def expand(self, lfmuser, page_len, so_far, criterion, example):
        """
        Expands a streak on the first page to the longest it can find across multiple pages.
        Potentially downgrades the criterion layer if the lower layer has far more matches.

        :param lfmuser: Last.fm user name
        :param page_len: Last.fm request page length
        :param so_far: First page of songs
        :param criterion: MostInteresting instance
        :param example: Example song
        :return: `(count, out_of, criterion, repr)` with count being the amount of matches for criterion it found,
            `out_of` being the amount of scrobbles that were looked at, `criterion` the (new, potentially downgraded)
            criterion and `repr` the most recent representative song of criterion.
        """
        self.logger.debug("Expanding")
        page_index = 1
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
        }

        prototype = {
            "top_index": 1,
            "top_matches": 0,
            "current_matches": 0,
            "repr": None,
        }
        counters = {
            MostInterestingType.ARTIST: prototype,
            MostInterestingType.ALBUM: prototype.copy(),
            MostInterestingType.TITLE: prototype.copy(),
        }
        current_index = 0
        current_page = so_far
        while True:
            improved = False
            for song in current_page:
                current_index += 1
                for current_criterion in MostInterestingType:
                    if self.interest_match(song, current_criterion, example):
                        c = counters[current_criterion]

                        # Set repr
                        if c["repr"] is None:
                            c["repr"] = song

                        # Calc matches
                        c["current_matches"] += 1
                        logging.debug("Comparison: %f > %f on song %s",
                                      c["current_matches"] / current_index,
                                      (c["top_matches"] - 2) / c["top_index"],
                                      str(current_index))
                        # This match improves our overall situation
                        if self.expand_formula(c["top_index"], c["top_matches"],
                                               current_index, c["current_matches"]):
                            improved = True
                            c["top_index"] = current_index
                            c["top_matches"] = c["current_matches"]

            self.logger.debug("Expand: Iteration done; counters: %s", pprint.pformat(counters))

            if not improved and page_index > 1:
                self.logger.debug("Expand: Done")
                break

            # Done, prepare next loop
            page_index += 1
            if page_index > self.get_config("limit"):
                break
            params["limit"] = page_len
            params["page"] = page_index
            self.logger.debug("Expand: Fetching page %i", page_index)
            current_page = self.build_songs(await self.request(params), first=False)

        self.logger.debug("counters: %s", str(counters))

        # Downgrade if necessary
        top_index = counters[criterion]["top_index"]
        top_matches = counters[criterion]["top_matches"]
        for el in [MostInterestingType.ALBUM, MostInterestingType.ARTIST]:
            downgrade_value = counters[el]["top_matches"] / self.get_config("mi_downgrade")
            self.logger.debug("Checking downgrade from %s to %s", str(criterion), str(el))
            self.logger.debug("Downgrade values: %s, %s", str(top_matches), str(downgrade_value))
            if top_matches <= downgrade_value:
                self.logger.debug("mi downgrade from %s to %s", str(criterion), str(el))
                criterion = el
                example = counters[el]["repr"]
                top_index = counters[el]["top_index"]
                top_matches = counters[el]["top_matches"]

        return top_matches, top_index, criterion, example

    def tiebreaker(self, scores, songs, mitype):
        """
        If multiple entries share the first place, decrease the score of all entries that are not the first
        to appear in the list of songs.

        :param scores: Scores entry dict as calculated by calc_scores
        :param songs: List of songs that the scores were calculated for
        :param mitype: MostInterestingType object that represents the criterion layer that is to be tie-broken
        """
        self.logger.debug("Scores to tiebreak: %s", pprint.pformat(scores))
        s = sorted(scores.keys(), key=lambda x: scores[x]["count"], reverse=True)
        first = [el for el in s if scores[el] == scores[s[0]]]
        found = False
        for song in songs:
            fact = None
            if mitype == MostInterestingType.ARTIST:
                fact = song["artist"]
            elif mitype == MostInterestingType.ALBUM:
                fact = song["artist"], song["album"]
            elif mitype == MostInterestingType.TITLE:
                fact = song["artist"], song["title"]
            if fact in first:
                first.remove(fact)
                found = True
                break
        assert found
        for el in first:
            scores[el] -= 1

    def calc_scores(self, songs, min_artist, min_album, min_title):
        """
        Counts the occurences of artists, songs and albums in a list of song dicts and assigns scores

        :param songs: list of songs
        :param min_artist: Amount of songs that have to have the same artist
        :param min_album: Amount of songs that have to have the same artist and album
        :param min_title: Amount of songs that have to have the same artist and album
        :return: nested dict that contains scores for every artist, song and album
        """
        r = {
            "artists": {},
            "albums": {},
            "titles": {},
        }
        i = 0
        for song in songs:
            if song["artist"] in r["artists"]:
                r["artists"][song["artist"]]["count"] += 1
            elif i < min_artist:
                r["artists"][song["artist"]] = {
                    "count": 1,
                    "distance": i,
                    "song": song
                }

            if (song["artist"], song["album"]) in r["albums"]:
                r["albums"][song["artist"], song["album"]]["count"] += 1
            elif i < min_album:
                r["albums"][song["artist"], song["album"]] = {
                    "count": 1,
                    "distance": i,
                    "song": song
                }

            if (song["artist"], song["title"]) in r["titles"]:
                r["titles"][song["artist"], song["title"]]["count"] += 1
            elif i < min_title:
                r["titles"][song["artist"], song["title"]] = {
                    "count": 1,
                    "distance": i,
                    "song": song
                }
            i += 1

        # Tie-breakers
        self.tiebreaker(r["artists"], songs, MostInterestingType.ARTIST)
        self.tiebreaker(r["albums"], songs, MostInterestingType.ALBUM)
        self.tiebreaker(r["titles"], songs, MostInterestingType.TITLE)

        return r

    async def most_interesting(self, ctx, user):
        """
        Finds the most current, most interesting facts in a user's history and sends them to ctx.

        :param ctx: Context
        :param user: User that whose history we are interested in
        :raises RuntimeError: Unexpected error (bug)
        """
        pagelen = 10
        min_album = self.get_config("min_album") * pagelen
        min_title = self.get_config("min_title") * pagelen
        min_artist = self.get_config("min_artist") * pagelen
        lfmuser = self.get_lastfm_user(user)
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": pagelen,
            "extended": 1,
        }
        response = await self.request(params, "GET")
        songs = self.build_songs(response)

        # Calc counts
        scores = self.calc_scores(songs[:pagelen], min_artist, min_album, min_title)
        best_artist = sorted(scores["artists"].keys(), key=lambda x: scores["artists"][x]["count"], reverse=True)[0]
        best_artist_count = scores["artists"][best_artist]["count"]
        best_artist = scores["artists"][best_artist]["song"]
        best_album = sorted(scores["albums"].keys(), key=lambda x: scores["albums"][x]["count"], reverse=True)[0]
        best_album_count = scores["albums"][best_album]["count"]
        best_album = scores["albums"][best_album]["song"]
        best_title = sorted(scores["titles"].keys(), key=lambda x: scores["titles"][x]["count"], reverse=True)[0]
        best_title_count = scores["titles"][best_title]["count"]
        best_title = scores["titles"][best_title]["song"]

        # Decide what is of the most interest
        mi = None
        # mi_score = 0
        mi_example = None
        if best_artist_count >= min_artist:
            mi = MostInterestingType.ARTIST
            # mi_score = best_artist_count
            mi_example = best_artist
        if best_album_count >= min_album:
            mi = MostInterestingType.ALBUM
            # mi_score = best_album_count
            mi_example = best_album
        if best_title_count >= min_title:
            mi = MostInterestingType.TITLE
            # mi_score = best_title_count
            mi_example = best_title
        if mi is None:
            # Nothing interesting found, send single song msg
            await ctx.send(self.listening_msg(user, songs[0]))
            return
        matches, total, mi, mi_example = await self.expand(lfmuser, pagelen, songs, mi, mi_example)

        # build msg
        if matches == total:
            matches = Lang.lang(self, "all")
        if mi_example.nowplaying:
            vp = Lang.lang(self, "most_interesting_base_present", gbu(user), "{}")
        else:
            # "x minutes ago"
            if mi_example is not None:
                paststr = hr_roughly(mi_example.timestamp,
                                     fstring=Lang.lang(self, "baseformat", "{}", "{}"),
                                     yesterday=Lang.lang(self, "yesterday"),
                                     seconds_sg=Lang.lang(self, "seconds_sg"),
                                     seconds=Lang.lang(self, "seconds_pl"),
                                     minutes_sg=Lang.lang(self, "minutes_sg"),
                                     minutes=Lang.lang(self, "minutes_pl"),
                                     hours_sg=Lang.lang(self, "hours_sg"),
                                     hours=Lang.lang(self, "hours_pl"),
                                     days_sg=Lang.lang(self, "days_sg"),
                                     days=Lang.lang(self, "days_pl"),
                                     weeks_sg=Lang.lang(self, "weeks_sg"),
                                     weeks=Lang.lang(self, "weeks_pl"),
                                     months_sg=Lang.lang(self, "months_sg"),
                                     months=Lang.lang(self, "months_pl"),
                                     years_sg=Lang.lang(self, "years_sg"),
                                     years=Lang.lang(self, "years_sg"))
                vp = Lang.lang(self, "most_interesting_past_format", gbu(user), paststr, "{}")
            else:
                vp = Lang.lang(self, "most_interesting_base_past", gbu(user), "{}")

        if mi == MostInterestingType.ARTIST:
            content = Lang.lang(self, "most_interesting_artist", mi_example.artist, matches, total)
        elif mi == MostInterestingType.ALBUM:
            content = Lang.lang(self, "most_interesting_album", mi_example.album, mi_example.artist, matches, total)
        elif mi == MostInterestingType.TITLE:
            song = mi_example.format_song()
            content = Lang.lang(self, "most_interesting_song", song, matches, total)
        else:
            raise RuntimeError("PANIC")
        msg = vp.format(content)

        quote = mi_example.quote()
        if quote is not None:
            msg = "{} _{}_".format(msg, quote)
        await ctx.send(msg)


def get_new_key(d):
    """
    :param d: dict
    :return: Largest key in dict `d` + 1
    """
    i = 1
    for key in d.keys():
        b = int(key)
        if b >= i:
            i = b + 1
    return i
