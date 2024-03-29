import logging
from typing import Tuple, Any, Dict, Optional

from botutils.restclient import Client as RestClient
from botutils.utils import add_reaction
from base.data import Lang

from plugins.lastfm.lfm_base import Song, Layer

AUTHURL = "https://accounts.spotify.com/api"
APIURL = "https://api.spotify.com/v1/"
LAYERMAP = {
    Layer.TITLE: "track",
    Layer.ALBUM: "album",
    Layer.ARTIST: "artist"
}


class NoCredentials(Exception):
    """
    Raised when a request is made without API authorization credentials being set.
    """
    pass


class AuthError(Exception):
    """
    Raised when authorization is not successful.
    """
    pass


class ApiError(Exception):
    """
    Raised when the API returns an error.
    """
    pass


class EmptyResult(Exception):
    """
    Raised when a spotify API call returns no results.
    """
    pass


class Client:
    """
    Implements the Spotify API.
    """
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
    def credentials(self) -> Tuple[str, str]:
        """
        :return: client_id, client_secret
        :raises NoCredentials: If API credentials are not set
        """
        r = (self._client_id, self._client_secret)
        if None in r:
            raise NoCredentials
        return r

    async def set_credentials(self, client_id: str, client_secret: str):
        """
        Sets client ID and client secret for authorization with the API.

        :param client_id: Client ID
        :param client_secret: Client secret
        """
        self._client_id = client_id
        self._client_secret = client_secret
        if client_id is not None and client_secret is not None:
            await self.auth()

    async def auth(self):
        """
        Refreshes the authorization token. Client ID and client secret need to be set for this.

        :raises AuthError: If authorization does not work (i.e. no token is returned by the auth api)
        """
        self.logger.debug("Refreshing authorization token")
        self.auth_client.auth_basic(*self.credentials)
        data = "grant_type=client_credentials"
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        r = await self.auth_client.request("token", data=data, method="POST", headers=h, encode_json=False)
        self.access_token = r.get("access_token", None)
        if self.access_token is None:
            raise AuthError

        self.api_client.auth_bearer(self.access_token)

    async def spotify_request(self, route: str, params: Optional[Dict[str, Any]] = None,
                              headers: Optional[Dict[str, Any]] = None, data: Any = None, method: str = "GET") -> Any:
        """
        Wrapper for Client.request() that handles re-auth if necessary (todo).

        :param route: endpoint route
        :param params: params
        :param headers: headers
        :param data: data
        :param method: HTTP method
        :return: response structure
        :raises ApiError: If the API returned an error (indicated by an "error" entry)
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

    @staticmethod
    def locate_response_element(response: Dict, layer: Layer) -> Any:
        """

        :param response: Spotify API response
        :param layer: API request layer
        :return: element that we're interested in
        :raises EmptyResult: If there is no element to be located in the response
        """
        if layer == Layer.TITLE:
            key = "tracks"
        elif layer == Layer.ALBUM:
            key = "albums"
        elif layer == Layer.ARTIST:
            key = "artists"
        else:
            assert False, "unknown layer {}".format(layer)

        r = response[key]["items"]
        if len(r) == 0:
            raise EmptyResult
        return r[0]

    async def search(self, searchstring: str, layer: Layer = Layer.TITLE) -> Song:
        """
        Implements Spotify's search API. Submits a search string and returns the first element found in the specified
        layer.

        :param searchstring: Search string
        :param layer: layer that is to be searched in
        :return: First song that is found with searchstring
        :raises EmptyResult: If the search returns no results
        """
        params = {
            "q": searchstring,
            "type": LAYERMAP[layer],
            "limit": 1,
        }
        r = await self.spotify_request("search", params=params, headers=self.headers)
        r = self.locate_response_element(r, layer)
        return Song.from_spotify_response(self.plugin, r, layer=layer)

    async def cmd_search(self, ctx, searchstring: str, layer: Layer):
        try:
            r = await self.search(searchstring, layer=layer)
        except EmptyResult:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self.plugin, "spotify_no_result"))
            return
        await ctx.send(r.spotify_links.get(layer, "no link found"))

    async def enrich_song(self, song: Song):
        """
        Adds spotify links to a song by fetching them from the API.

        :param song: Song object to be enriched
        :raises EmptyResult: If enrichment fails because spotify search returns no results
        """
        self.logger.debug("Enriching song %s; layer: %s", song, song.layer)
        if song.layer == Layer.ARTIST:
            searchstring = song.artist
        else:
            searchstring = "{} {}".format(song.artist, song.get_layer_name(song.layer))

        params = {
            "q": searchstring,
            "type": LAYERMAP[song.layer],
            "limit": 1,
        }
        r = await self.spotify_request("search", params=params, headers=self.headers)
        song.set_spotify_links_from_response(self.locate_response_element(r, song.layer))
