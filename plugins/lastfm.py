import logging
from enum import Enum
from datetime import datetime
import time
import random
import pprint
from urllib.error import HTTPError

import discord
from discord.ext import commands

from base import BasePlugin, NotLoadable, NotFound
from conf import Config, Lang, Storage
from botutils.converters import get_best_username as gbu
from botutils.timeutils import hr_roughly
from botutils.stringutils import paginate
from botutils.utils import write_debug_channel
from botutils.questionnaire import Questionnaire, Question, QuestionType, Cancelled
from botutils.restclient import Client


baseurl = "https://ws.audioscrobbler.com/2.0/"


class NotRegistered(Exception):
    def __init__(self, plugin):
        self.plugin = plugin
        super().__init__()

    async def default(self, ctx):
        await ctx.message.add_reaction(Lang.CMDERROR)
        await ctx.send(Lang.lang(self.plugin, "not_registered"))


class UnknownResponse(Exception):
    def __init__(self, msg, usermsg):
        self.user_message = usermsg
        super().__init__(msg)


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

    def quote(self, p=None):
        if p is None:
            p = self.plugin.get_config("quote_p")

        q = self.plugin.get_quotes(self.artist, self.title)
        if q is not None:
            q = random.choice(q)
            if p is not None and random.choices([True, False], weights=[p, 1 - p])[0]:
                return q
        return None

    def format_song(self):
        r = Lang.lang(self.plugin, "listening_song_base", self.title, self.artist)
        if self.loved:
            r = "{} {}".format(Lang.lang(self.plugin, "loved"), r)
        return r

    def __getitem__(self, key):
        if key == "artist":
            return self.artist
        elif key == "album":
            return self.album
        elif key == "title":
            return self.title
        elif key == "nowplaying":
            return self.nowplaying
        elif key == "loved":
            return self.loved
        raise KeyError

    def __repr__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)

    def __str__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)


class Plugin(BasePlugin, name="LastFM"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.logger = logging.getLogger(__name__)
        self.client = Client(baseurl)
        self.conf = Config.get(self)
        if not self.conf.get("apikey", ""):
            raise NotLoadable("API Key not found")

        self.perf_total_time = None
        self.perf_lastfm_time = None
        self.perf_request_count = 0
        self.perf_reset_timers()

        self.base_config = {
            "limit": [int, 5],
            "min_artist": [float, 0.5],
            "min_album": [float, 0.4],
            "min_title": [float, 0.5],
            "mi_downgrade": [float, 1.5],
            "quote_p": [float, 0.5],
        }

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
            "state_done": Lang.lang(self, "quote_done")
        }
        self.cmd_order = [
            "now",
            "register",
            "deregister",
            "profile"
        ]

    def get_config(self, key):
        return Config.get(self).get(key, self.base_config[key][1])

    def default_config(self):
        return {}

    def default_storage(self, container=None):
        if container is None:
            return {
                "users": {}
            }
        elif container == "quotes":
            return {
                "version": 1,
                "quotes": []
            }
        else:
            raise RuntimeError

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format(command.name))

    def command_description(self, command):
        msg = Lang.lang(self, "desc_{}".format(command.name))
        if command.name == "werbinich":
            msg += Lang.lang(self, "options_werbinich")
        return msg

    def command_usage(self, command):
        if command.name == "werbinich":
            return Lang.lang(self, "usage_{}".format(command.name))
        else:
            raise NotFound()

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

    def request(self, params, method="GET"):
        params["format"] = "json"
        params["api_key"] = self.conf["apikey"]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Geckarbot/{}".format(self.bot.VERSION)
        }
        before = self.perf_timenow()
        r = self.client.make_request("", params=params, headers=headers, method=method)
        after = self.perf_timenow()
        self.perf_add_lastfm_time(after - before)
        return r

    def get_lastfm_user(self, user: discord.User):
        r = Storage.get(self)["users"].get(user.id, None)
        if r is None:
            raise NotRegistered(self)
        else:
            return r

    def perf_reset_timers(self):
        self.perf_lastfm_time = 0.0
        self.perf_total_time = 0.0
        self.perf_request_count = 0

    def perf_add_lastfm_time(self, t):
        self.perf_lastfm_time += t

    def perf_add_total_time(self, t):
        self.perf_total_time += t
        self.perf_request_count += 1

    def get_quotes(self, artist, title):
        for el in Storage.get(self, container="quotes").get("quotes", []):
            if el[0].lower() == artist.lower() and el[1].lower() == title.lower():
                return el[2]
        return None

    @staticmethod
    def perf_timenow():
        return time.clock_gettime(time.CLOCK_MONOTONIC)

    @commands.group(name="lastfm", invoke_without_command=True)
    async def lastfm(self, ctx):
        self.perf_reset_timers()
        before = self.perf_timenow()
        try:
            async with ctx.typing():
                await self.most_interesting(ctx, ctx.author)
        except NotRegistered as e:
            await e.default(ctx)
            return
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    @commands.has_role(Config().BOT_ADMIN_ROLE_ID)
    @lastfm.command(name="config", aliases=["set"], hidden=True)
    async def cmd_config(self, ctx, key=None, value=None):
        # list
        if key is None and value is None:
            msg = []
            for key in self.base_config:
                msg.append("{}: {}".format(key, self.get_config(key)))
            for msg in paginate(msg, msg_prefix="```", msg_suffix="```"):
                await ctx.send(msg)
            return

        # set
        if key not in self.base_config:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Invalid config key")
            return
        try:
            value = self.base_config[key][0](value)
        except (TypeError, ValueError):
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send("Invalid value")
            return
        oldval = self.get_config(key)
        Config.get(self)[key] = value
        Config.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        await ctx.send("Changed {} value from {} to {}".format(key, oldval, value))

    @lastfm.command(name="register")
    async def register(self, ctx, lfmuser: str):
        info = self.get_user_info(lfmuser)
        if info is None:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "user_not_found"))
            return
        if "user" not in info:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(self, "error")
            await write_debug_channel("Error: \"user\" not in {}".format(info))
            return
        Storage.get(self)["users"][ctx.author.id] = lfmuser
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @lastfm.command(name="deregister")
    async def deregister(self, ctx):
        if ctx.author.id in Storage.get(self)["users"]:
            del Storage.get(self)["users"][ctx.author.id]
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        else:
            await ctx.message.add_reaction(Lang.CMDNOCHANGE)

    @lastfm.command(name="profile", usage="<User>")
    async def cmd_profile(self, ctx, user: discord.User):
        try:
            user = self.get_lastfm_user(user)
        except NotRegistered as e:
            await e.default(ctx)
            return
        await ctx.send("http://last.fm/user/{}".format(user))

    @lastfm.command(name="performance", hidden=True)
    async def perf(self, ctx):
        decdigits = 3
        total = round(self.perf_total_time, decdigits)
        lastfm = round(self.perf_lastfm_time, decdigits)
        percent = int(round(lastfm * 100 / total))
        await ctx.send(Lang.lang(self, "performance", lastfm, total, percent, self.perf_request_count))

    @lastfm.command(name="page", hidden=True)
    async def history(self, ctx, page: int):
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
        songs = self.build_songs(self.request(params))
        for i in range(len(songs)):
            songs[i] = self.listening_msg(ctx.author, songs[i])
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        for msg in paginate(songs):
            await ctx.send(msg)
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    def quote_cb(self, question, question_queue):
        if question.answer == question.data["new"]:
            self.logger.debug("Got answer new")
            question.data["result_scrobble"] = False
            return question_queue
        elif question.answer == question.data["scrobble"]:
            self.logger.debug("Got answer scrobble")
            question.data["result_scrobble"] = True
            return [question.data["q_quote"]]
        assert False

    @lastfm.command(name="quote", hidden=True)
    async def cmd_quote(self, ctx):
        # Acquire last song for first questionnaire route
        try:
            lfmuser = self.get_lastfm_user(ctx.author)
        except NotRegistered as e:
            await e.default(ctx)
            return

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
            "extended": 1,
        }
        response = self.request(params)
        song = self.build_songs(response)[0]

        # Build Questionnaire
        q_artist = Question("Artist?", QuestionType.TEXT, lang=self.lang_question)
        q_title = Question("Title?", QuestionType.TEXT, lang=self.lang_question)
        q_quote = Question("Quote?", QuestionType.TEXT, lang=self.lang_question)
        data = {
            "song": song,
            "q_quote": q_quote,
            "scrobble": Lang.lang(self, "quote_scrobble"),
            "new": Lang.lang(self, "quote_new"),
            "result_scrobble": None,
        }
        answers = [Lang.lang(self, "quote_scrobble"), Lang.lang(self, "quote_new")]
        q_target = Question(Lang.lang(self, "quote_target", song.format_song()), QuestionType.SINGLECHOICE,
                            answers=answers, callback=self.quote_cb, data=data)
        questions = [q_target, q_artist, q_title, q_quote]
        questionnaire = Questionnaire(self.bot, ctx.author, questions, lang=self.lang_questionnaire)

        try:
            await questionnaire.interrogate()
        except Cancelled:
            return
        except (KeyError, RuntimeError):
            await ctx.message.add_reaction(Lang.CMDERROR)
            return
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

        assert data["result_scrobble"] is not None
        if data["result_scrobble"]:
            artist = song.artist
            title = song.title
        else:
            artist = q_artist.answer
            title = q_title.answer

        quotes = self.get_quotes(artist, title)
        if quotes is None:
            quotes = []
            ta = [artist, title, quotes]
            Storage.get(self, container="quotes")["quotes"].append(ta)
        self.logger.debug("Adding quote: {} to {}".format(q_quote.answer, quotes))
        quotes.append(q_quote.answer)
        Storage.save(self, container="quotes")

    @lastfm.command(name="now", aliases=["listening"])
    async def cmd_now(self, ctx, user=None):
        self.perf_reset_timers()
        before = self.perf_timenow()
        if user is None:
            user = ctx.author
        else:
            # find mentioned user
            try:
                user = await commands.MemberConverter().convert(ctx, user)
            except (commands.CommandError, IndexError):
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "user_not_found", user))
                return
        try:
            lfmuser = self.get_lastfm_user(user)
        except NotRegistered as e:
            await e.default(ctx)
            return

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
            "extended": 1,
        }

        async with ctx.typing():
            response = self.request(params)
            song = self.build_songs(response)[0]

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

    def get_user_info(self, lfmuser):
        params = {
            "method": "user.getInfo",
            "user": lfmuser
        }
        try:
            return self.request(params)
        except HTTPError:
            return None

    def get_by_path(self, structure, path, default=None, strict=False):
        result = structure
        for el in path:
            try:
                result = result[el]
            except (TypeError, KeyError, IndexError):
                if strict:
                    raise UnknownResponse("{} not found in structure".format(el),
                                          Lang.lang(self, "error"))
                return default
        return result

    def build_songs(self, response, append_to=None, first=True):
        """
        Builds song dicts out of a response.
        :param response: Response from the Last.fm API
        :param append_to: Append resulting songs to this list instead of building a new one.
        :param first: If False, removes a leading "nowplaying" song if existant.
        :return: List of song dicts that have the keys `artist`, `title`, `album`, `nowplaying`
        """
        tracks = response["recenttracks"]["track"]
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
        if criterion == MostInterestingType.ARTIST:
            if song["artist"] == example["artist"]:
                return True
            else:
                return False
        if criterion == MostInterestingType.ALBUM:
            if song["artist"] == example["artist"] and song["album"] == example["album"]:
                return True
            else:
                return False

        if criterion == MostInterestingType.TITLE:
            if song["artist"] == example["artist"] and song["title"] == example["title"]:
                return True
            else:
                return False

    @staticmethod
    def expand_formula(top_index, top_matches, current_index, current_matches):
        return current_matches / current_index > (top_matches - 2) / top_index

    def expand(self, lfmuser, page_len, so_far, criterion, example):
        """
        Expands a streak on the first page to the longest it can find across multiple pages.
        Potentially downgrades the criterion layer if the lower layer has far more matches.
        :param lfmuser: Last.fm user name
        :param page_len: Last.fm request page length
        :param so_far: First page of songs
        :param criterion: MostInteresting instance
        :param example: Example song
        :return: `(count, out_of, criterion)` with count being the amount of matches for criterion it found,
        out_of being the amount of scrobbles that were looked at, criterion the (new, potentially downgraded) criterion.
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
                        c["current_matches"] += 1
                        logging.debug("Comparison: {} > {} on song {}"
                                      .format(c["current_matches"] / current_index,
                                              (c["top_matches"] - 2) / c["top_index"],
                                              current_index))
                        # This match improves our overall situation
                        if self.expand_formula(c["top_index"], c["top_matches"],
                                               current_index, c["current_matches"]):
                            improved = True
                            c["top_index"] = current_index
                            c["top_matches"] = c["current_matches"]

            self.logger.debug("Expand: Iteration done; counters: {}".format(pprint.pformat(counters)))

            if not improved and page_index > 1:
                self.logger.debug("Expand: Done")
                break

            # Done, prepare next loop
            page_index += 1
            if page_index > self.get_config("limit"):
                break
            params["limit"] = page_len
            params["page"] = page_index
            self.logger.debug("Expand: Fetching page {}".format(page_index))
            current_page = self.build_songs(self.request(params), first=False)

        self.logger.debug("counters: {}".format(counters))

        # Downgrade if necessary
        top_index = counters[criterion]["top_index"]
        top_matches = counters[criterion]["top_matches"]
        for el in [MostInterestingType.ALBUM, MostInterestingType.ARTIST]:
            downgrade_value = counters[el]["top_matches"] / self.get_config("mi_downgrade")
            self.logger.debug("Checking downgrade from {} to {}".format(criterion, el))
            self.logger.debug("Downgrade values: {}, {}".format(top_matches, downgrade_value))
            if top_matches <= downgrade_value:
                self.logger.debug("mi downgrade from {} to {}".format(criterion, el))
                criterion = el
                top_index = counters[el]["top_index"]
                top_matches = counters[el]["top_matches"]

        return top_matches, top_index, criterion

    def tiebreaker(self, scores, songs, mitype):
        """
        If multiple entries share the first place, decrease the score of all entries that are not the first
        to appear in the list of songs.
        :param scores: Scores entry dict as calculated by calc_scores
        :param songs: List of songs that the scores were calculated for
        :param mitype: MostInterestingType object that represents the criterion layer that is to be tie-broken
        :return:
        """
        self.logger.debug("Scores to tiebreak: {}".format(pprint.pformat(scores)))
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
        response = self.request(params, "GET")
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
        mi_score = 0
        mi_example = None
        if best_artist_count >= min_artist:
            mi = MostInterestingType.ARTIST
            mi_score = best_artist_count
            mi_example = best_artist
        if best_album_count >= min_album:
            mi = MostInterestingType.ALBUM
            mi_score = best_album_count
            mi_example = best_album
        if best_title_count >= min_title:
            mi = MostInterestingType.TITLE
            mi_score = best_title_count
            mi_example = best_title
        if mi is None:
            # Nothing interesting found, send single song msg
            await ctx.send(self.listening_msg(user, songs[0]))
            return
        matches, total, mi = self.expand(lfmuser, pagelen, songs, mi, mi_example)

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
                                     seconds=Lang.lang(self, "seconds"),
                                     minutes=Lang.lang(self, "minutes"),
                                     hours=Lang.lang(self, "hours"),
                                     days=Lang.lang(self, "days"),
                                     weeks=Lang.lang(self, "weeks"),
                                     months=Lang.lang(self, "months"),
                                     years=Lang.lang(self, "years"))
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
