import logging

from botutils.restclient import Client as RestClient

from plugins.lastfm.lfm_base import Song, Layer

AUTHURL = "https://accounts.spotify.com/api"
APIURL = "https://api.spotify.com/v1/"
LAYERMAP = {
    Layer.TITLE: "track",
    Layer.ALBUM: "album",
    Layer.ARTIST: "artist"
}


class NoCredentials(Exception):
    pass


class AuthError(Exception):
    pass


class ApiError(Exception):
    pass


class Client:
    def __init__(self, plugin):
        self.plugin = plugin
        self._client_id = None
        self._client_secret = None
        self.auth_client = RestClient(AUTHURL)
        self.api_client = RestClient(APIURL)
        self.access_token = None
        self.logger = logging.getLogger(__name__)

        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    @property
    def credentials(self):
        r = (self._client_id, self._client_secret)
        if None in r:
            raise NoCredentials
        return r

    async def set_credentials(self, client_id, client_secret):
        self._client_id = client_id
        self._client_secret = client_secret
        if client_id is not None and client_secret is not None:
            await self.auth()

    async def auth(self):
        self.logger.debug("Refreshing authorization token")
        self.auth_client.auth_basic(*self.credentials)
        data = "grant_type=client_credentials"
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        r = await self.auth_client.request("token", data=data, method="POST", headers=h, encode_json=False)
        self.access_token = r.get("access_token", None)
        if self.access_token is None:
            raise AuthError

        self.api_client.auth_bearer(self.access_token)

    async def spotify_request(self, route, params=None, headers=None, data=None, method="GET"):
        """
        Wrapper for Client.request() that handles re-auth if necessary (todo).

        :param route: endpoint route
        :param params: params
        :param headers: headers
        :param data: data
        :param method: HTTP method
        :return:
        """
        had_auth_error = False
        r = None
        for _ in range(2):
            r = await self.api_client.request(route, params=params, headers=headers, data=data, method=method)
            error = r.get("error", None)

            if error:
                # Do re-auth and try again
                if error["status"] == 401 and not had_auth_error:
                    had_auth_error = True
                    await self.auth()

                # Raise whatever else came around
                else:
                    raise ApiError(str(r))
            else:
                break
        return r

    async def search(self, searchstring, layer=Layer.TITLE):
        params = {
            "q": searchstring,
            "type": LAYERMAP[layer],
            "limit": 1,
        }
        r = await self.spotify_request("search", params=params, headers=self.headers)
        return Song.from_spotify_response(self.plugin, r["tracks"]["items"][0])

    async def enrich_song(self, song: Song):
        """
        Adds spotify links to a song.

        :param song: Song object to be enriched
        """
        searchstring = "{} - {}".format(song.artist, song.title)
        params = {
            "q": searchstring,
            "type": LAYERMAP[Layer.TITLE],
            "limit": 1,
        }
        r = await self.spotify_request("search", params=params, headers=self.headers)
        song.set_spotify_links_from_response(r["tracks"]["items"][0])
