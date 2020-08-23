#!/usr/bin/env python3

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode
import base64
import logging

# Config #######
verbose = False
################

version = "1.3"


"""
Changelog:
1.3:
    added URL params
1.2:
    changed url to remove trailing /
1.1:
    added parse_json flag to make_request
1.0:
    added basic auth
"""


def log(s):
    if verbose:
        print(s)


class AuthError(Exception):
    pass


def maskprint(d, prefix=""):
    """
    Prints the dictionary d but replaces any "password" values with ***
    """
    found = []
    candidates = ["password", "pw", "Password", "passwort", "Passwort"]
    for el in candidates:
        if el in d:
            found.append(el)

    if found:
        d = d.copy()
        for el in found:
            d[el] = "***"

    log(prefix + str(d))


class Client:
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

    @staticmethod
    def _normalize_url_part(part):
        """
        Normalizes a URL part, i.e. removes "/" at the beginning and adds one at the end
        *TODO* urlencode
        :param part: URL part to normalize
        :return:
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

    def set_url_appendix(self, s):
        """
        Sets an appendix for the host URL (useful for things that don't change like authentication)
        :param s: appendix
        :return: None
        """
        self.url_appendix = Client._normalize_url_part(s)

    def parse_response(self, response):
        """
        Parses a json response from the API.
        :param response: response to parse
        :return: representation of the json response
        """
        return self.decoder.decode(response)

    def parse_request_data(self, data):
        """
        Parses a dict to urlencoded json
        :param data: the dict that is to be urlencoded
        :return:
        """
        if data is None:
            return None
        return self.encoder.encode(data)

    def url(self, endpoint="", appendix=None, params=None):
        """
        Build the URL with url, appendix and endpoint
        :param endpoint: endpoint, defaults to ""
        :param appendix: URL appendix, overrides the one set with set_url_appendix()
        :param params: URL params as a dict
        :return: built URL
        """
        if not appendix:
            appendix = self.url_appendix
        url = self.base_url + appendix + endpoint
        if url.endswith("/"):
            url = url[:-1]

        # params
        if params:
            params = urlencode(params)
            url = url + "?" + params

        return url

    def auth_basic(self, username, password):
        """
        Sets authentication header for basic authentication.
        :param username: Username
        :param password: Password
        :return: None
        """
        self.credentials["username"] = username
        self.credentials["password"] = password
        self.auth = "basic"

    @staticmethod
    def build_session_cookie(session):
        return {"cookie": session["name"] + "=" + session["value"]}

    def make_request(self, endpoint, appendix=None, params=None, data=None,
                     headers=None, method="GET", parse_json=True):
        """
        does the http and json part
        :param endpoint: REST resource / end point
        :param appendix: URL appendix for this request. Overrides the one set with set_appendix().
        :param params: URL parameters as a dict
        :param data: dict that is being sent as json
        :param headers: http headers dict
        :param method: http method ("GET", "POST" etc)
        :param parse_json: Treat response as json and parse it
        :return: parsed response
        """
        if not headers:
            headers = {}

        if appendix:
            appendix = Client._normalize_url_part(appendix)
        headers_to_add = {}
        endpoint = Client._normalize_url_part(endpoint)

        if data is not None:
            data = self.parse_request_data(data)
            data = data.encode("utf-8")
            maskprint(self.decoder.decode(data.decode("utf-8")), prefix="data: ")
        else:
            self.logger.debug("data: ")

        if self.cookie is not None:
            headers_to_add.update(self.cookie)

        # base64 auth (initial use case: jira)
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

        maskprint(headers, prefix="headers: ")
        url = self.url(endpoint=endpoint, appendix=appendix, params=params)
        request = urllib.request.Request(url,
                                         data=data, headers=headers, method=method)
        self.logger.debug("url: {}".format(url))

        self.logger.debug("doing request")
        response = urllib.request.urlopen(request).read().decode("utf-8")
        self.logger.debug("Response: {}".format(response))

        if parse_json:
            response = self.parse_response(response)
        return response
