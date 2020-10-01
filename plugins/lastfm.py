from urllib.error import HTTPError

import discord
from discord.ext import commands

from base import BasePlugin, NotLoadable, NotFound
from conf import Config, Lang, Storage
from botutils import utils
from botutils.converters import get_best_username as gbu
from botutils.restclient import Client


baseurl = "https://ws.audioscrobbler.com/2.0/"


def get_by_path(structure, path, default=None):
    result = structure
    for el in path:
        try:
            result = result[el]
        except (TypeError, KeyError, IndexError):
            return default
    return result


class Plugin(BasePlugin, name="LastFM"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.client = Client(baseurl)
        self.conf = Config.get(self)
        if not self.conf.get("apikey", ""):
            raise NotLoadable("API Key not found")

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

    def request(self, params, method):
        params["format"] = "json"
        params["api_key"] = self.conf["apikey"]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Geckarbot/{}".format(self.bot.VERSION)
        }
        return self.client.make_request("", params=params, headers=headers, method=method)

    def get_lastfm_user(self, user: discord.User):
        return Storage.get(self)["users"].get(user.id, None)

    @commands.group(name="lastfm", invoke_without_command=True)
    async def lastfm(self, ctx):
        await ctx.send("Hello world!")
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @lastfm.command(name="register")
    async def register(self, ctx, lfmuser: str):
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

    @lastfm.command(name="listening")
    async def listening(self, ctx, user=None):
        if user is None:
            user = ctx.author
        else:
            # find mentioned user
            try:
                user = await commands.MemberConverter().convert(ctx, user)
            except (commands.CommandError, IndexError):
                await ctx.send(Lang.lang(self, "user_not_found", user))
                await ctx.message.add_reaction(Lang.CMDERROR)
                return
        lfmuser = self.get_lastfm_user(user)

        params = {
            "method": "user.getRecentTracks",
            "user": lfmuser,
            "limit": 1,
        }

        async with ctx.typing():
            response = self.request(params, "GET")
            song = get_by_path(response, ["recenttracks", "track", 0])
            nowplaying = get_by_path(song, ["@attr", "nowplaying"])
            artist = get_by_path(song, ["artist", "#text"])
            title = get_by_path(song, ["name"])
            album = get_by_path(song, ["album", "#text"], default="unknown")

            if artist is None or title is None or album is None:
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "error"))
                await utils.write_debug_channel(self.bot, "artist, title or album not found in {}".format(response))
                return

            if nowplaying == "true":
                msg = "listening"
            else:
                msg = "listening_last"

            await ctx.send(Lang.lang(self, msg, gbu(user), title, artist, album))
