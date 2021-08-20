from datetime import datetime
from enum import Enum
from typing import List
import pprint
import random

from botutils.utils import write_debug_channel
from data import Lang


class Layer(Enum):
    TITLE = 0
    ALBUM = 1
    ARTIST = 2


class Song:
    """
    Represents an occurence of a title in a scrobble history, i.e. a scrobble.
    """
    def __init__(self, plugin, artist, album, title, nowplaying=False, timestamp=None, loved=False, layer=Layer.TITLE):
        self.plugin = plugin
        self.artist = artist
        self.album = album
        self.title = title
        self.nowplaying = nowplaying
        self.timestamp = timestamp
        self.loved = loved
        self.layer = layer

        # spotify
        self.spotify_links = {}
        self.featurings: List[str] = []

    @classmethod
    def from_lastfm_response(cls, plugin, element):
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

    @staticmethod
    def parse_artists(element):
        """

        :param element: spotify response element r["artists"]
        :return: artist name, featurings list
        """
        artist = None
        featurings = []
        first = True
        for el in element:
            if first:
                first = False
                artist = el["name"]
            else:
                featurings.append(el["name"])
        return artist, featurings

    @classmethod
    def from_spotify_response(cls, plugin, element, layer=Layer.TITLE):
        """
        Builds a Song object from a spotify API response.

        :param plugin: Plugin object
        :param element: response["tracks"]["items"][i]
        :param layer: layer that was requested from spotify
        :return: Song object that represents `element`
        """
        title = None
        album = None
        artist = None
        featurings = None

        # Request was for title
        if layer == layer.TITLE:
            title = element["name"]
            album = element["album"]["name"]
            artist, featurings = cls.parse_artists(element["artists"])

        # Request was for album
        if layer == layer.ALBUM:
            album = element["name"]
            artist, featurings = cls.parse_artists(element["artists"])

        if layer == layer.ARTIST:
            artist = element["name"]

        r = cls(plugin, artist, album, title, layer=layer)
        r.set_spotify_links_from_response(element)
        return r

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

    def format(self, reverse=False, loved=True):
        """
        :param reverse: Formats to something like "song by artist" instead of "artist - song"
        :param loved: Adds a heart emoji prefix if this song is loved
        :return: Nice readable representation of the song according to lang string
        """
        if not reverse:
            r = Lang.lang(self.plugin, "listening_song_base", self.title, self.artist)
        else:
            r = Lang.lang(self.plugin, "listening_song_base_reverse", self.artist, self.title)
        if loved and self.loved:
            r = "{} {}".format(Lang.lang(self.plugin, "loved"), r)
        return r

    def set_spotify_link(self, layer, link):
        self.spotify_links[layer] = link

    def set_spotify_links_from_response(self, element):
        """
        Gets all relevant spotify links out of element.

        :param element: response["tracks"]["items"][i]
        """
        if self.layer == Layer.TITLE:
            self.spotify_links[Layer.ARTIST] = element["artists"][0]["external_urls"]["spotify"]
            self.spotify_links[Layer.ALBUM] = element["album"]["external_urls"]["spotify"]
            self.spotify_links[Layer.TITLE] = element["external_urls"]["spotify"]
        elif self.layer == Layer.ALBUM:
            self.spotify_links[Layer.ARTIST] = element["artists"][0]["external_urls"]["spotify"]
            self.spotify_links[Layer.ALBUM] = element["external_urls"]["spotify"]
        elif self.layer == Layer.ARTIST:
            self.spotify_links[Layer.ARTIST] = element["external_urls"]["spotify"]
        else:
            assert False, "unknown layer {}".format(self.layer)

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

    def __eq__(self, other):
        return self.artist == other.artist and self.album == other.album and self.title == other.title

    def __repr__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)

    def __str__(self):
        return "<plugins.lastfm.Song object; {}: {} ({})>".format(self.artist, self.title, self.album)
