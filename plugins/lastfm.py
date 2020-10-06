from enum import Enum
import time
from urllib.error import HTTPError

import discord
from discord.ext import commands

from base import BasePlugin, NotLoadable, NotFound
from conf import Config, Lang, Storage
from botutils.converters import get_best_username as gbu
from botutils.stringutils import paginate
from botutils.utils import write_debug_channel
from botutils.restclient import Client


baseurl = "https://ws.audioscrobbler.com/2.0/"


class NotRegistered(Exception):
    pass


class UnknownResponse(Exception):
    def __init__(self, msg, usermsg):
        self.user_message = usermsg
        super().__init__(msg)


class MostInterestingType(Enum):
    ARTIST = 0
    ALBUM = 1
    TITLE = 2


class Plugin(BasePlugin, name="LastFM"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.client = Client(baseurl)
        self.conf = Config.get(self)
        if not self.conf.get("apikey", ""):
            raise NotLoadable("API Key not found")

        self.perf_total_time = None
        self.perf_lastfm_time = None
        self.perf_request_count = 0
        self.perf_reset_timers()

    def default_config(self):
        return {}

    def default_storage(self):
        return {
            "users": {}
        }

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
            raise NotRegistered
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
        except NotRegistered:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "not_registered"))
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

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

    @lastfm.command(name="performance", hidden=True)
    async def perf(self, ctx):
        decdigits = 3
        total = round(self.perf_total_time, decdigits)
        lastfm = round(self.perf_lastfm_time, decdigits)
        percent = int(round(lastfm * 100 / total))
        await ctx.send(Lang.lang(self, "performance", lastfm, total, percent, self.perf_request_count ))

    @lastfm.command(name="page", hidden=True)
    async def history(self, ctx, page: int):
        self.perf_reset_timers()
        before = self.perf_timenow()
        pagelen = 10
        try:
            lfmuser = self.get_lastfm_user(ctx.author)
        except NotRegistered:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "not_registered"))
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

    @lastfm.command(name="listening")
    async def listening(self, ctx, user=None):
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
        except NotRegistered:
            await ctx.send(Lang.lang(self, "not_registered"))
            return

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
        }

        async with ctx.typing():
            response = self.request(params, "GET")
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
        msg = Lang.lang(self, "listening_song_base", song["title"], song["artist"])
        if song["album"]:
            msg = Lang.lang(self, "listening_song_album", msg, song["album"])
        if song["nowplaying"]:
            msg = Lang.lang(self, "listening_base_present", gbu(user), msg)
        else:
            msg = Lang.lang(self, "listening_base_past", gbu(user), msg)
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

    @staticmethod
    def sanitize_album(album):
        return album.strip()

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

    def build_songs(self, response, append_to=None):
        """
        Builds song dicts out of a response.
        :param response: Response from the Last.fm API
        :param append_to: Append resulting songs to this list instead of building a new one.
        :return: List of song dicts that have the keys `artist`, `title`, `album`, `nowplaying`
        """
        tracks = self.get_by_path(response, ["recenttracks", "track"])
        r = [] if append_to is None else append_to
        for el in tracks:
            song = {
                "artist": self.get_by_path(el, ["artist", "#text"], strict=True),
                "title": self.get_by_path(el, ["name"], strict=True),
                "album": self.sanitize_album(self.get_by_path(el, ["album", "#text"], default="unknown")),
                "nowplaying": self.get_by_path(el, ["@attr", "nowplaying"], default="false"),
            }
            if song["nowplaying"] == "true":
                song["nowplaying"] = True
            else:
                if song["nowplaying"] != "false":
                    write_debug_channel("WARNING: lastfm: unexpected \"nowplaying\": {}".format(song["nowplaying"]))
                song["nowplaying"] = False
            r.append(song)
        return r

    @staticmethod
    def interest_match(song, criterion, fact):
        if criterion == MostInterestingType.ARTIST:
            if song["artist"] == fact:
                return True
            else:
                return False
        if criterion == MostInterestingType.ALBUM:
            if song["artist"] == fact[0] and song["album"] == fact[1]:
                return True
            else:
                return False

        if criterion == MostInterestingType.TITLE:
            if song["artist"] == fact[0] and song["title"] == fact[1]:
                return True
            else:
                return False

    def expand(self, lfmuser, so_far, criterion, fact):
        """
        Expands a streak on the first page to the longest it can find
        :param lfmuser: Last.fm user name
        :param so_far: First page of songs
        :param criterion: MostInteresting instance
        :param fact: fact
        :return: `(count, out_of)` with count being the amount of matches for criterion it found
        """
        limit = 5
        page_len = len(so_far)
        page_index = 1
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
        }

        top_song_index = 1
        top_matches = 0
        current_song_index = 0
        current_matches = 0
        current_page = so_far
        while True:
            improved = False
            for song in current_page:
                current_song_index += 1
                if self.interest_match(song, criterion, fact):
                    current_matches += 1
                    # This match improves our overall situation
                    if current_matches / current_song_index > (top_matches - 1) / top_song_index:
                        improved = True
                        top_song_index = current_song_index
                        top_matches = current_matches

            if not improved and page_index > 1:
                break

            # Done, prepare next loop
            page_index += 1
            if page_index > limit:
                break
            params["limit"] = page_len
            params["page"] = page_index
            current_page = self.build_songs(self.request(params, "GET"))
            if len(current_page) > page_len:
                if len(current_page) != page_len + 1:
                    raise RuntimeError("PANIC")
                current_page = current_page[1:]

        return top_matches, top_song_index

    @staticmethod
    def calc_scores(songs):
        """
        Counts the occurences of artists, songs and albums in a list of song dicts.
        :param songs: list of songs
        :return: nested dict that contains scores for every artist, song and album
        """
        r = {
            "artists": {},
            "albums": {},
            "titles": {},
        }
        for song in songs:
            if song["artist"] in r["artists"]:
                r["artists"][song["artist"]] += 1
            else:
                r["artists"][song["artist"]] = 1

            if (song["artist"], song["album"]) in r["albums"]:
                r["albums"][song["artist"], song["album"]] += 1
            else:
                r["albums"][song["artist"], song["album"]] = 1

            if (song["artist"], song["title"]) in r["titles"]:
                r["titles"][song["artist"], song["title"]] += 1
            else:
                r["titles"][song["artist"], song["title"]] = 1
        return r

    async def most_interesting(self, ctx, user):
        pagelen = 10
        factor = 0.65
        lfmuser = self.get_lastfm_user(user)
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": pagelen,
        }
        response = self.request(params, "GET")
        songs = self.build_songs(response)

        # Calc counts
        scores = self.calc_scores(songs)
        best_artist = sorted(scores["artists"].keys(), key=lambda x: scores["artists"][x], reverse=True)[0]
        best_artist_count = scores["artists"][best_artist]
        best_album = sorted(scores["albums"].keys(), key=lambda x: scores["albums"][x], reverse=True)[0]
        best_album_count = scores["albums"][best_album]
        best_album_artist, best_album = best_album
        best_title = sorted(scores["titles"].keys(), key=lambda x: scores["titles"][x], reverse=True)[0]
        best_title_count = scores["titles"][best_title]
        best_title_artist, best_title = best_title

        # Decide what is of the most interest
        mi = None
        mi_score = 0
        mi_fact = None
        tobreak = len(songs) * factor
        if best_artist_count > tobreak:
            mi = MostInterestingType.ARTIST
            mi_score = best_artist_count
            mi_fact = best_artist
        if best_album_count > tobreak:
            mi = MostInterestingType.ALBUM
            mi_score = best_album_count
            mi_fact = best_album_artist, best_album
        if best_title_count > tobreak:
            mi = MostInterestingType.TITLE
            mi_score = best_title_count
            mi_fact = best_title_artist, best_title
        if mi is None:
            # Nothing interesting found, send single song msg
            await ctx.send(self.listening_msg(user, songs[0]))
            return

        # expand and build msg
        matches, total = self.expand(lfmuser, songs, mi, mi_fact)
        if matches == total:
            matches = Lang.lang(self, "all")
        if songs[0]["nowplaying"]:
            base = "most_interesting_base_present"
        else:
            base = "most_interesting_base_past"
        if mi == MostInterestingType.ARTIST:
            content = Lang.lang(self, "most_interesting_artist", mi_fact, matches, total)
            msg = Lang.lang(self, base, gbu(user), content)
        elif mi == MostInterestingType.ALBUM:
            content = Lang.lang(self, "most_interesting_album", mi_fact[1], mi_fact[0], matches, total)
            msg = Lang.lang(self, base, gbu(user), content)
        elif mi == MostInterestingType.TITLE:
            song = Lang.lang(self, "listening_song_base", mi_fact[1], mi_fact[0])
            content = Lang.lang(self, "most_interesting_song", song, matches, total)
            msg = Lang.lang(self, base, gbu(user), content)
        else:
            raise RuntimeError("PANIC")
        await ctx.send(msg)
