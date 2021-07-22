#!/usr/bin/env python3

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode
import base64
import logging
import asyncio

import aiohttp


class AuthError(Exception):
    """Raisen on authentication errors"""


class Client:
    """Client for HTTP requests, e.g. for REST APIs"""

    def __init__(self, url):
        self.credentials = {}

        # build api url
        self.base_url = Client._normalize_url_part(url)
        self.url_appendix = ""
        if not self.base_url.startswith("http://") and not self.base_url.startswith("https://"):
            self.base_url = "http://" + self.base_url

        self.cookie = None
        self.auth = None

        self.decoder = json.JSONDecoder()
        self.encoder = json.JSONEncoder()

        self.logger = logging.getLogger(__name__)

        self.aiosession = aiohttp.ClientSession()

    @staticmethod
    def _normalize_url_part(part) -> str:
        """
        Normalizes a URL part, i.e. removes "/" at the beginning and adds one at the end
        *TODO* urlencode
        :param part: URL part to normalize
        :return: Normalized URL part
        """
        while True:
            if not part.startswith("/"):
                break
            part = part[1:]

        while True:
            if not part.endswith("/"):
                break
            part = part[:-1]

        if part == "":
            return part
        return part + "/"

    def set_url_appendix(self, s: str):
        """
        Sets an appendix for the host URL (useful for things that don't change like authentication)

        :param s: appendix
        """
        self.url_appendix = Client._normalize_url_part(s)

    def parse_response(self, response: str):
        """
        Parses a json response from the API.

        :param response: response to parse
        :return: representation of the json response
        """
        return self.decoder.decode(response)

    def parse_request_data(self, data: dict):
        """
        Parses a dict to urlencoded json

        :param data: the dict that is to be urlencoded
        :return: Urlencoded `data` (defaults to None if data is None)
        """
        if data is None:
            return None
        return self.encoder.encode(data)

    def url(self, endpoint: str = "", appendix: str = None, params: dict = None):
        """
        Build the URL with url, appendix and endpoint

        :param endpoint: endpoint, defaults to ""
        :param appendix: URL appendix, overrides the one set with set_url_appendix()
        :param params: URL params as a dict
        :return: built URL
        """
        endpoint = Client._normalize_url_part(endpoint)
        if appendix:
            appendix = Client._normalize_url_part(appendix)
        else:
            appendix = self.url_appendix
        url = self.base_url + appendix + endpoint
        if url.endswith("/"):
            url = url[:-1]

        # params
        if params:
            params = urlencode(params)
            url = url + "?" + params

        return url

    def auth_basic(self, username: str, password: str):
        """
        Sets authentication header for basic authentication.

        :param username: Username
        :param password: Password
        """
        self.credentials["username"] = username
        self.credentials["password"] = password
        self.auth = "basic"

    @staticmethod
    def _build_session_cookie(session) -> dict:
        return {"cookie": session["name"] + "=" + session["value"]}

    def _build_headers(self, headers):
        if not headers:
            headers = {}
        headers_to_add = {}

        if self.cookie is not None:
            headers_to_add.update(self.cookie)

        # basic auth
        if self.auth == "basic":
            auth = self.credentials["username"] + ":" + self.credentials["password"]
            auth = base64.encodebytes(auth.encode("utf-8"))
            auth = "Basic ".encode("utf-8") + auth
            auth = auth.decode("utf-8").replace("\n", "")
            auth = {"Authorization": auth}
            headers_to_add.update(auth)

        # Build headers
        headers = headers.copy()
        headers.update(headers_to_add)
        return headers

    async def request(self, endpoint, appendix=None, params=None, data=None,
                      headers=None, method="GET", parse_json=True):
        """
        Sends a http request.

        :param endpoint: REST resource / end point
        :param appendix: URL appendix for this request. Overrides the one set with set_appendix().
        :param params: URL parameters as a dict
        :param data: dict that is being sent as json
        :param headers: http headers dict
        :param method: http method ("GET", "POST" etc)
        :param parse_json: Treat response as json and parse it
        :return: parsed response
        :raises RuntimeError: Raised if method is an unknown http method
        """
        headers = self._build_headers(headers)
        url = self.url(endpoint=endpoint, appendix=appendix, params=params)
        data = self.parse_request_data(data)
        self._maskprint(data, prefix="data: ")

        if method == "GET":
            f = self.aiosession.get
        elif method == "POST":
            f = self.aiosession.post
        elif method == "PUT":
            f = self.aiosession.put
        elif method == "DELETE":
            f = self.aiosession.delete
        elif method == "HEAD":
            f = self.aiosession.head
        elif method == "OPTIONS":
            f = self.aiosession.options
        elif method == "PATCH":
            f = self.aiosession.patch
        else:
            raise RuntimeError("Unknown HTTP method: {}".format(method))

        self.logger.debug("Doing async http request to %s", url)
        async with f(url, headers=headers, data=data) as response:
            response = await response.text()
        self.logger.debug("Response: %s", response)
        if parse_json:
            response = json.loads(response)
        return response

    def make_request(self, endpoint, appendix=None, params=None, data=None,
                     headers=None, method="GET", parse_json=True):
        """
        Sends a http request.

        :param endpoint: REST resource / end point
        :param appendix: URL appendix for this request. Overrides the one set with set_appendix().
        :param params: URL parameters as a dict
        :param data: dict that is being sent as json
        :param headers: http headers dict
        :param method: http method ("GET", "POST" etc)
        :param parse_json: Treat response as json and parse it
        :return: parsed response
        """
        if data is not None:
            data = self.parse_request_data(data)
            data = data.encode("utf-8")
            self._maskprint(self.decoder.decode(data.decode("utf-8")), prefix="data: ")

        headers = self._build_headers(headers)
        url = self.url(endpoint=endpoint, appendix=appendix, params=params)
        request = urllib.request.Request(url,
                                         data=data, headers=headers, method=method)

        self.logger.debug("Doing sync http request to %s", url)
        response = urllib.request.urlopen(request).read().decode("utf-8")
        self.logger.debug("Response: %s", response)

        if parse_json:
            response = self.parse_response(response)
        return response

    def __del__(self):
        asyncio.create_task(self.aiosession.close())

    def _maskprint(self, d, prefix=""):
        """
        Prints the dictionary d but replaces any `"password"` values with `***`
        """
        if d is None:
            return

        found = []
        candidates = ["password", "pw", "Password", "passwort", "Passwort"]
        for el in candidates:
            if el in d:
                found.append(el)

        if found:
            d = d.copy()
            for el in found:
                d[el] = "***"

        self.logger.debug("%s%s", prefix, str(d))
