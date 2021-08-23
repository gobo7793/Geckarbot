from urllib.error import HTTPError
from typing import List, Optional

from botutils.restclient import Client
from botutils.utils import add_reaction
from data import Lang

from plugins.lastfm.lfm_base import Song

BASEURL = "https://ws.audioscrobbler.com/2.0/"


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


class Api:
    """
    Implements access to the Last.fm API.
    """
    def __init__(self, plugin):
        self.plugin = plugin
        self.client = Client(BASEURL)

    async def request(self, params, method="GET"):
        """
        Does a request to last.fm API and parses the reponse to a dict.

        :param params: URL parameters
        :param method: HTTP method
        :return: Response dict
        """
        params["format"] = "json"
        params["api_key"] = self.plugin.conf["apikey"]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Geckarbot/{}".format(self.plugin.bot.VERSION)
        }
        before = self.plugin.perf_timenow()
        r = await self.client.request("", params=params, headers=headers, method=method)
        after = self.plugin.perf_timenow()
        self.plugin.perf_add_lastfm_time(after - before)
        return r

    def build_songs(self, response, append_to=None, first: bool = True) -> List[Song]:
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
            raise UnexpectedResponse("\"recenttracks\" not in response", Lang.lang(self.plugin, "api_error")) from e
        r = [] if append_to is None else append_to
        done = False
        for el in tracks:
            song = Song.from_lastfm_response(self.plugin, el)
            if not first and not done and song.nowplaying:
                done = True
                continue
            r.append(Song.from_lastfm_response(self.plugin, el))
        return r

    async def get_recent_tracks(self, lfmuser, page=1, pagelen=10,
                                extended: bool = False, first: bool = True) -> List[Song]:
        """
        Gets a list of lfmuser's recent scrobbles

        :param lfmuser: lfm user name
        :param page: page index, counting starts at 1
        :param pagelen: page length
        :param extended: whether to get extended song info (includes e.g. loved)
        :param first: If False, removes a leading "nowplaying" song if existant.
        :return: list of songs
        """
        extended = 1 if extended else 0
        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "page": page,
            "limit": pagelen,
            "extended": extended,
        }
        return self.build_songs(await self.request(params), first=first)

    async def get_current_scrobble(self, lfmuser) -> Optional[Song]:
        """
        Gets the song lfmuser is currently scrobbling.

        :param lfmuser: Last.fm username
        :return: The song lfmuser is currently scrobbling; None if there is none.
        """
        song = (await self.get_recent_tracks(lfmuser, page=1, pagelen=1))[0]
        if song.nowplaying:
            return song
        return None

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
