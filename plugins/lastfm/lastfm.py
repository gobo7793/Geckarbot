import logging
from typing import Union, Optional
import time
import random
import re
import pprint

import discord
from discord.ext import commands

from base import BasePlugin, NotLoadable
from data import Config, Lang, Storage
from botutils.converters import get_best_username as gbu, get_best_user, convert_member
from botutils.timeutils import to_unix_str, TimestampStyle, hr_roughly
from botutils.stringutils import paginate
from botutils.utils import write_debug_channel, add_reaction, helpstring_helper, execute_anything_sync
from botutils.questionnaire import Questionnaire, Question, QuestionType, Cancelled
from botutils.setter import ConfigSetter
from botutils.permchecks import check_mod_access, check_admin_access

from plugins.lastfm.api import Api, UnexpectedResponse
from plugins.lastfm.presence import LfmPresenceMessage
from plugins.lastfm.lfm_base import Song, Layer
from plugins.lastfm.spotify import Client as Spotify, AuthError, EmptyResult

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


class Plugin(BasePlugin, name="LastFM"):
    def __init__(self, bot):
        super().__init__(bot)

        self.logger = logging.getLogger(__name__)
        self.migrate()
        self.api = Api(self)
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
            "mi_enable_downgrade": [bool, True],
            "mi_downgrade": [float, 1.5],
            "mi_nowplaying_bonus": [bool, True],
            "timestampstyle_discord": [bool, True],
            "quote_p": [float, 0.5],
            "max_quote_length": [int, 100],
            "quote_restrict_del": [bool, True],
            "presence": [bool, True],
            "presence_tick": [int, 60],
            "presence_include_listener": [bool, True],
            "presence_artist_only": [bool, False],
            "presence_title_only": [bool, True],
            "presence_artist_and_title": [bool, False],
            "presence_order_artist_title": [bool, False],
            "presence_order_user_song": [bool, False],
            "presence_optout": [bool, True],
            "spotify_is_default": [bool, False]
        }
        self.config_setter = ConfigSetter(self, self.base_config)
        self.config_setter.add_switch("presence_title_only", "presence_artist_only", "presence_artist_and_title")

        # Presence
        self.presence_handler = LfmPresenceMessage(self)

        # Spotify
        self.spotify = Spotify(self)
        sptf_cfg = Config.get(self, container="spotify")
        c = self.spotify.set_credentials(sptf_cfg.get("client_id", None), sptf_cfg.get("client_secret", None))
        execute_anything_sync(c)

        # Quote lang dicts
        self.lang_question = {
            "or": Lang.lang(self, "or"),
            "answer_cancel": Lang.lang(self, "cancel"),
            "answer_list_sc": "",
        }
        self.lang_questionnaire = {
            "intro": "",
            "intro_howto_cancel": "",
            "result_rejected": Lang.lang(self, "quote_invalid"),
            "state_cancelled": Lang.lang(self, "cancelled"),
            "state_done": "",
            "answer_list_sc": Lang.lang(self, "quote_answer_list_sc"),
        }
        self.lang_quote_del = {
            "intro": "",
            "intro_howto_cancel": "",
            "or": Lang.lang(self, "or"),
            "answer_cancel": Lang.lang(self, "cancel"),
            "answer_list_sc": "",
            "result_rejected": Lang.lang(self, "quote_del_invalid_answer"),

            "state_cancelled": Lang.lang(self, "cancelled"),
            "state_done": ""
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

        storage = Storage.get(self)
        if "version" not in storage:
            for userid in storage["users"]:
                lfmuser = storage["users"][userid]
                storage["users"][userid] = {
                    "lfmuser": lfmuser
                }
            storage["version"] = 1
            Storage.save(self)

    def get_config(self, key):
        return Config.get(self).get(key, self.base_config[key][1])

    def default_config(self, container=None):
        if container and container != "spotify":
            raise RuntimeError("Unknown config container {}".format(container))
        return {}

    def default_storage(self, container=None):
        if container is None:
            return {
                "version": 1,
                "users": {}
            }
        if container == "quotes":
            return {
                "version": 2,
                "quotes": {}
            }
        raise RuntimeError("Unknown storage container {}".format(container))

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        if command.qualified_name == "lastfm quote del":
            args = [Lang.lang(self, "del_restricted")] if self.get_config("quote_restrict_del") else []
            return Lang.lang(self, "desc_lastfm_quote_del", *args)
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

        # Add !spotify
        for cmd in self.get_commands():
            if cmd.name == "spotify":
                r.append(cmd)

        return r

    @property
    def show_presence(self):
        """
        Indicates whether the presence is supposed to be registered / displayed
        """
        return self.get_config("presence")

    def get_lastfm_user(self, user: discord.User):
        """
        :param user: discord user
        :return: Corresponding last.fm user
        :raises NotRegistered: `user` did not register their last.fm username
        """
        r = Storage.get(self)["users"].get(user.id, None)
        if r is None:
            raise NotRegistered(self)
        return r["lfmuser"]

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

    def del_quote(self, artist: str, title: str, quote_id: int):
        """
        Deletes a quote from storage.

        :param artist: Artist
        :param title: Title
        :param quote_id: Quote ID (inner ID, specific to artist-title-combination)
        :raises RuntimeError: If the quote does not exist
        """
        quotes = Storage.get(self, container="quotes")["quotes"]
        key = None
        for el in quotes:
            if quotes[el]["artist"].lower() == artist.lower() and quotes[el]["title"].lower() == title.lower():
                key = el
                break
        if not key or quote_id not in quotes[key]["quotes"]:
            raise RuntimeError("quote {} - {}: {} not found".format(artist, title, quote_id))

        del quotes[key]["quotes"][quote_id]
        if not quotes[key]["quotes"]:
            del quotes[key]
        Storage.save(self, container="quotes")

    @staticmethod
    def perf_timenow():
        return time.clock_gettime(time.CLOCK_MONOTONIC)

    def parse_args(self, args, author) -> dict:
        """
        Parses a list of args that was passed to a regular output cmd. Fishes for a discord user and "spotify".
        Ignores arguments that do not fit.

        :param args: list of arguments
        :param author: ctx.author (default case for "user")
        :return: dict of resulting settings; keys: "spotify": bool, "user": discord.Member
        """
        r = {
            "user": author,
            "spotify": self.get_config("spotify_is_default")
        }

        user_found = False
        for arg in args:
            if arg.lower() == "spotify":
                r["spotify"] = True
                continue

            member = convert_member(arg)
            if member and not user_found:
                user_found = True
                r["user"] = member
                continue

        return r

    @commands.group(name="lastfm", invoke_without_command=True)
    async def cmd_lastfm(self, ctx, *args):
        self.perf_reset_timers()
        before = self.perf_timenow()

        args = self.parse_args(args, ctx.author)
        try:
            async with ctx.typing():
                await self.most_interesting(ctx, args["user"], spotify=args["spotify"])
        except (NotRegistered, UnexpectedResponse) as e:
            await e.default(ctx)
            return
        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    @commands.has_role(Config().BOT_ADMIN_ROLE_ID)
    @cmd_lastfm.command(name="set", aliases=["config"], hidden=True)
    async def cmd_set(self, ctx, key=None, value=None):
        if key is None:
            await self.config_setter.list(ctx)
            return
        if value is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        await self.config_setter.set_cmd(ctx, key, value)

        # specific handlers that have to do something on value change
        if key == "presence":
            self.presence_handler.config_update()

    @cmd_lastfm.command(name="register")
    async def cmd_register(self, ctx, lfmuser: str):
        info = await self.api.get_user_info(lfmuser)
        if info is None:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "user_not_found", lfmuser))
            return
        if "user" not in info:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(self, "error")
            await write_debug_channel("Error: \"user\" not in {}".format(info))
            return
        Storage.get(self)["users"][ctx.author.id] = {"lfmuser": lfmuser}
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

        try:
            songs = await self.api.get_recent_tracks(lfmuser, page=page, pagelen=pagelen)
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

    async def quote_so_far_helper(self, user, song, restrict_to_user=False):
        """
        Sends a list of current quotes to User `user`'s DM

        :param user: User to send the quotes to
        :param song: Song instance
        :param restrict_to_user: Flag that indicates whether only `user`'s quotes are to be shown
        """
        self.logger.debug("Sending current quotes for %s to %s", str(song), str(user))
        msg = [Lang.lang(self, "quote_existing_quotes")]
        quotes = self.get_quotes(song.artist, song.title)
        for key in quotes:
            author = get_best_user(quotes[key]["author"])
            if restrict_to_user and user != author:
                continue
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
        if question.answer == question.data["scrobble"]:
            self.logger.debug("Got answer scrobble")
            question.data["result_scrobble"] = True
            return question_queue
        assert False

    async def quote_new_song_cb(self, question, question_queue):
        """
        Is called when the answer for the question "Title?" comes in

        :param question: Question object
        :param question_queue: list of Question objects that were to be posed after this
        :return: question_queue
        """
        song = Song(self, question.data["q_artist"].answer, "", question.data["q_title"].answer)
        question.data["song"] = song
        question.data["result_scrobble"] = False
        return question_queue

    async def quote_acquire_song(self, ctx, user, question_lang_key) -> Song:
        """
        Asks `user` via DM for the song that a quote is to be added to and builds a Song instance out of it.

        :param ctx: Context
        :param user: Discord user
        :param question_lang_key: Lang.lang key for the question
        :return: Song that a quote is to be added to
        """
        # Fetch scrobbled song
        lfmuser = self.get_lastfm_user(user)
        song = (await self.api.get_recent_tracks(lfmuser, pagelen=1, extended=True))[0]

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
        q_target = Question(Lang.lang(self, question_lang_key, song.format(reverse=True)), QuestionType.SINGLECHOICE,
                            answers=answers, data=cargo, lang=self.lang_question, callback=self.quote_scrobble_cb)
        questions = [q_target]
        questionnaire = Questionnaire(self.bot, ctx.author, questions, "lastfm acquire quote",
                                      lang=self.lang_questionnaire)

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
        await self.quote_so_far_helper(ctx.author, song)
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

    @cmd_quote.command(name="del", aliases=["rm", "remove"])
    async def cmd_quote_del(self, ctx):
        user = ctx.author
        restricted = self.get_config("quote_restrict_del") and not (check_admin_access(user) or check_mod_access(user))

        # Acquire song
        try:
            song = await self.quote_acquire_song(ctx, ctx.author, "quote_del_target")
        except Cancelled:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return
        except (NotRegistered, UnexpectedResponse) as e:
            await e.default(ctx)
            return

        # Acquire quotes
        candidates = self.get_quotes(song.artist, song.title)
        quotes = {}
        for el in candidates.values():
            if not restricted or user.id == el["author"]:
                quotes[el] = el
        if not quotes:
            await user.send(Lang.lang(self, "quote_del_empty"))
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        # Show quotes the user is allowed to delete
        msgs = []
        for key, quote in quotes.items():
            author = get_best_user(quote["author"])
            author = gbu(author) if author is not None else Lang.lang(self, "quote_unknown_user")
            msg = Lang.lang(self, "quote_list_entry", quote["quote"], author)
            msgs.append("**#{}** {}".format(key, msg))
        for msg in paginate(msgs, prefix=Lang.lang(self, "quote_del_list_prefix") + "\n"):
            await user.send(msg)

        # Delete dialog
        q_del = Question(Lang.lang(self, "quote_del_question"), QuestionType.SINGLECHOICE,
                         answers=[str(el) for el in quotes], allow_empty=True, lang=self.lang_quote_del)
        dialog = Questionnaire(self.bot, user, [q_del], "lastfm quote del", lang=self.lang_quote_del)
        try:
            await dialog.interrogate()
        except Cancelled:
            await user.send(Lang.lang(self, "quote_del_nochange"))
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)
            return

        # Delete
        self.del_quote(song.artist, song.title, int(q_del.answer))
        await user.send(Lang.lang(self, "quote_del_success", q_del.answer))
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def append_spotify_link(self, msg: str, song: Song, layer: Layer) -> str:
        """
        Appends the corresponding spotify layer link to a lastfm message.
        Does nothing if the spotify search fails.

        :param msg: Existing lastfm message
        :param song: song
        :param layer: Specified layer
        :return: New message (ideally including the spotify link)
        """
        try:
            await self.spotify.enrich_song(song)
            return msg + "\n" + song.spotify_links[layer]
        except EmptyResult:
            pass
        return msg

    @cmd_lastfm.command(name="listening")
    async def cmd_listening(self, ctx, *args):
        args_d = self.parse_args(args, ctx.author)
        if self.presence_handler.is_currently_shown:
            song = self.presence_handler.state.cur_song.format(reverse=True)
            listener = self.presence_handler.state.cur_listener_dc
            msg = Lang.lang(self, "presence_listening", song, gbu(listener))

            if args_d["spotify"]:
                msg = await self.append_spotify_link(msg, self.presence_handler.state.cur_song, Layer.TITLE)

            await ctx.send(msg)
            return
        await self.cmd_now(ctx, *args)

    @cmd_lastfm.command(name="now")
    async def cmd_now(self, ctx, *args):
        self.perf_reset_timers()
        before = self.perf_timenow()

        args = self.parse_args(args, ctx.author)
        sg3p = False
        if args["user"] != ctx.author:
            sg3p = True
        try:
            lfmuser = self.get_lastfm_user(args["user"])
        except NotRegistered as e:
            await e.default(ctx, sg3p=sg3p)
            return

        async with ctx.typing():
            try:
                song = (await self.api.get_recent_tracks(lfmuser, pagelen=1, extended=True))[0]
            except UnexpectedResponse as e:
                await e.default(ctx)
                return

            msg = self.listening_msg(args["user"], song)

            if args["spotify"]:
                msg = await self.append_spotify_link(msg, song, Layer.TITLE)

        await ctx.send(msg)

        after = self.perf_timenow()
        self.perf_add_total_time(after - before)

    @cmd_lastfm.command(name="presence")
    async def cmd_presence_opt(self, ctx, opt_arg: Optional[str]):
        # update presence
        if opt_arg == "update":
            await self.presence_handler.update()
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        # actual optout setting
        key = "presence_optout"
        userlist = Storage.get(self)["users"]
        userid = ctx.author.id

        if userid not in userlist.keys():
            await ctx.send(Lang.lang(self, "not_registered"))
            return

        # send current status
        if opt_arg is None:
            if userlist[userid].get(key, not self.get_config(key)):
                await ctx.send(Lang.lang(self, "presence_status_optout"))
                return
            await ctx.send(Lang.lang(self, "presence_status_optin"))
            return

        # set status
        err = False
        if opt_arg in ("opt in", "optin", "opt-in", "opt_in"):
            userlist[userid][key] = False
        elif opt_arg in ("opt out", "optout", "opt-out", "opt_out"):
            userlist[userid][key] = True
        elif opt_arg == "default":
            del userlist[userid][key]
        else:
            err = True

        if err:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return

        Storage.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    def listening_msg(self, user, song):
        """
        Builds a "x is listening to y" message string.

        :param user: User that is listening
        :param song: song dict
        :return: Message string that is ready to be sent
        """
        if song.title.strip().lower().startswith("keine lust") and random.choice([True, True, False]):
            return "Keine Lust :("
        msg = song.format(reverse=True)
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

    @commands.group(name="spotify", invoke_without_command=True)
    async def cmd_spotify(self, ctx, *args):
        user = self.parse_args(args, ctx.author)["author"]

        async with ctx.typing():
            # Get user
            try:
                lfmuser = self.get_lastfm_user(user)
            except NotRegistered:
                await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
                return

            # Fetch song from lastfm
            try:
                song = (await self.api.get_recent_tracks(lfmuser, pagelen=1))[0]
            except UnexpectedResponse as e:
                await e.default(ctx)
                return

            # Fetch same song from spotify
            await self.spotify.enrich_song(song)
            await ctx.send(song.spotify_links[Layer.TITLE])

    @cmd_spotify.command(name="credentials", hidden=True)
    async def cmd_spotify_credentials(self, ctx, client_id: str, client_secret: str):
        if not check_admin_access(ctx.author):
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return

        # reset to no credentials
        if not client_id or not client_secret:
            client_id = None
            client_secret = None

        Config.get(self, container="spotify")["client_id"] = client_id
        Config.get(self, container="spotify")["client_secret"] = client_secret
        Config.save(self, container="spotify")

        try:
            await self.spotify.set_credentials(client_id, client_secret)
        except AuthError:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_spotify.group(name="search", invoke_without_command=True)
    async def cmd_spotify_search(self, ctx, *, searchterm):
        await self.spotify.cmd_search(ctx, searchterm, Layer.TITLE)

    @cmd_spotify_search.command(name="artist", aliases=["interpret"], hidden=True)
    async def cmd_spotify_search_artist(self, ctx, *, searchterm):
        await self.spotify.cmd_search(ctx, searchterm, Layer.ARTIST)

    @cmd_spotify_search.command(name="album", hidden=True)
    async def cmd_spotify_search_album(self, ctx, *, searchterm):
        await self.spotify.cmd_search(ctx, searchterm, Layer.ALBUM)

    @cmd_spotify_search.command(name="title", aliases=["song", "track"], hidden=True)
    async def cmd_spotify_search_title(self, ctx, *, searchterm):
        await self.spotify.cmd_search(ctx, searchterm, Layer.TITLE)

    @staticmethod
    def interest_match(song, criterion, example):
        """
        Checks whether a song is in the same mi type criterion category as another.

        :param song: Song object
        :param criterion: Layer object
        :param example:
        :return: True if `song` and `example` have matching categories according to `criterion`
        """
        if criterion == Layer.ARTIST:
            return song["artist"] == example["artist"]

        if criterion == Layer.ALBUM:
            return song["artist"] == example["artist"] and song["album"] == example["album"]

        if criterion == Layer.TITLE:
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

    async def expand(self, lfmuser, page_len, so_far, layer, example):
        """
        Expands a streak on the first page to the longest it can find across multiple pages.
        Potentially downgrades the criterion layer if the lower layer has far more matches.

        :param lfmuser: Last.fm user name
        :param page_len: Last.fm request page length
        :param so_far: First page of songs
        :param layer: Layer instance
        :param example: Example song
        :return: `(count, out_of, criterion, repr)` with count being the amount of matches for criterion it found,
            `out_of` being the amount of scrobbles that were looked at, `criterion` the (new, potentially downgraded)
            criterion and `repr` the most recent representative song of criterion.
        """
        self.logger.debug("Expanding")
        page_index = 1

        prototype = {
            "top_index": 1,
            "top_matches": 0,
            "current_matches": 0,
            "repr": None,
        }
        counters = {
            Layer.ARTIST: prototype,
            Layer.ALBUM: prototype.copy(),
            Layer.TITLE: prototype.copy(),
        }
        current_index = 0
        current_page = so_far
        while True:
            improved = False
            for song in current_page:
                current_index += 1
                for current_criterion in Layer:
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
            self.logger.debug("Expand: Fetching page %i", page_index)
            current_page = await self.api.get_recent_tracks(lfmuser, page=page_index, pagelen=page_len, first=False)

        self.logger.debug("counters: %s", str(counters))

        if not self.get_config("mi_enable_downgrade"):
            return counters[layer]["top_matches"], counters[layer]["top_index"], layer, example

        # Downgrade if necessary
        top_index = counters[layer]["top_index"]
        top_matches = counters[layer]["top_matches"]
        for el in [Layer.ALBUM, Layer.ARTIST]:
            downgrade_value = counters[el]["top_matches"] / self.get_config("mi_downgrade")
            self.logger.debug("Checking downgrade from %s to %s", str(layer), str(el))
            self.logger.debug("Downgrade values: %s, %s", str(top_matches), str(downgrade_value))
            if top_matches <= downgrade_value:
                self.logger.debug("mi downgrade from %s to %s", str(layer), str(el))
                layer = el
                example = counters[el]["repr"]
                top_index = counters[el]["top_index"]
                top_matches = counters[el]["top_matches"]

        return top_matches, top_index, layer, example

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
            if mitype == Layer.ARTIST:
                fact = song["artist"]
            elif mitype == Layer.ALBUM:
                fact = song["artist"], song["album"]
            elif mitype == Layer.TITLE:
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
        # pylint: disable=unused-argument
        r = {
            "artists": {},
            "albums": {},
            "titles": {},
        }
        i = 0
        nowplaying = None
        for song in songs:
            if song.nowplaying:
                nowplaying = song

            if song.artist in r["artists"]:
                r["artists"][song.artist]["count"] += 1
                r["artists"][song.artist]["score"] += 1
            # elif i < min_artist:
            else:
                r["artists"][song.artist] = {
                    "count": 1,
                    "score": 1,
                    "distance": i,
                    "song": song
                }

            if (song.artist, song.album) in r["albums"]:
                r["albums"][song.artist, song.album]["count"] += 1
                r["albums"][song.artist, song.album]["score"] += 1
            # elif i < min_album:
            else:
                r["albums"][song.artist, song.album] = {
                    "count": 1,
                    "score": 1,
                    "distance": i,
                    "song": song
                }

            if (song.artist, song.title) in r["titles"]:
                r["titles"][song.artist, song.title]["count"] += 1
                r["titles"][song.artist, song.title]["score"] += 1
            # elif i < min_title:
            else:
                r["titles"][song.artist, song.title] = {
                    "count": 1,
                    "score": 1,
                    "distance": i,
                    "song": song
                }
            i += 1

        # Bonus for nowplaying
        if nowplaying and self.get_config("mi_nowplaying_bonus"):
            artist = r["artists"][nowplaying.artist]
            if artist["count"] >= self.get_config("min_artist") * len(songs):
                artist["score"] *= 2
            album = r["albums"][nowplaying.artist, nowplaying.album]
            if album["count"] >= self.get_config("min_album") * len(songs):
                album["score"] *= 2
            title = r["titles"][nowplaying.artist, nowplaying.title]
            if title["count"] >= self.get_config("min_title") * len(songs):
                title["score"] *= 2

        self.logger.debug("scores: %s", r)

        # Tie-breakers
        self.tiebreaker(r["artists"], songs, Layer.ARTIST)
        self.tiebreaker(r["albums"], songs, Layer.ALBUM)
        self.tiebreaker(r["titles"], songs, Layer.TITLE)

        return r

    async def most_interesting(self, ctx, user, spotify=False):
        """
        Finds the most current, most interesting facts in a user's history and sends them to ctx.

        :param ctx: Context
        :param user: User that whose history we are interested in
        :param spotify: Include a spotify link
        :raises RuntimeError: Unexpected error (bug)
        """
        pagelen = 10
        min_album = self.get_config("min_album") * pagelen
        min_title = self.get_config("min_title") * pagelen
        min_artist = self.get_config("min_artist") * pagelen
        lfmuser = self.get_lastfm_user(user)
        songs = await self.api.get_recent_tracks(lfmuser, pagelen=pagelen, extended=True)

        # Calc counts
        scores = self.calc_scores(songs[:pagelen], min_artist, min_album, min_title)
        best_artist = sorted(scores["artists"].keys(), key=lambda x: scores["artists"][x]["score"], reverse=True)[0]
        best_artist_count = scores["artists"][best_artist]["count"]
        best_artist = scores["artists"][best_artist]["song"]
        best_album = sorted(scores["albums"].keys(), key=lambda x: scores["albums"][x]["score"], reverse=True)[0]
        best_album_count = scores["albums"][best_album]["count"]
        best_album = scores["albums"][best_album]["song"]
        best_title = sorted(scores["titles"].keys(), key=lambda x: scores["titles"][x]["score"], reverse=True)[0]
        best_title_count = scores["titles"][best_title]["count"]
        best_title = scores["titles"][best_title]["song"]

        # Decide what is of the most interest
        mi = None
        # mi_score = 0
        mi_example = None
        if best_artist_count >= min_artist:
            mi = Layer.ARTIST
            # mi_score = best_artist_count
            mi_example = best_artist
        if best_album_count >= min_album:
            mi = Layer.ALBUM
            # mi_score = best_album_count
            mi_example = best_album
        if best_title_count >= min_title:
            mi = Layer.TITLE
            # mi_score = best_title_count
            mi_example = best_title
        if mi is None:
            # Nothing interesting found, send single song msg
            msg = self.listening_msg(user, songs[0])
            if spotify:
                await self.spotify.enrich_song(songs[0])
                msg += "\n" + songs[0].spotify_links[Layer.TITLE]
            await ctx.send(msg)
            return
        matches, total, mi, mi_example = await self.expand(lfmuser, pagelen, songs, mi, mi_example)
        self.logger.debug("Setting song layer to %s", mi)
        mi_example.layer = mi

        # build msg
        if matches == total:
            matches = Lang.lang(self, "all")
        if mi_example.nowplaying:
            vp = Lang.lang(self, "most_interesting_base_present", gbu(user), "{}")
        else:
            # "x minutes ago"
            if mi_example is not None:
                if self.get_config("timestampstyle_discord"):
                    paststr = to_unix_str(mi_example.timestamp, style=TimestampStyle.RELATIVE)
                else:
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

        if mi == Layer.ARTIST:
            content = Lang.lang(self, "most_interesting_artist", mi_example.artist, matches, total)
        elif mi == Layer.ALBUM:
            content = Lang.lang(self, "most_interesting_album", mi_example.album, mi_example.artist, matches, total)
        elif mi == Layer.TITLE:
            song = mi_example.format()
            content = Lang.lang(self, "most_interesting_song", song, matches, total)
        else:
            assert False, "unknown layer {}".format(mi)
        msg = vp.format(content)

        quote = mi_example.quote()
        if quote is not None:
            msg = "{} _{}_".format(msg, quote)

        if spotify:
            msg = await self.append_spotify_link(msg, mi_example, mi)
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
