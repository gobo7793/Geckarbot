import logging
import random
from typing import Optional

import discord

from subsystems.presence import PresenceMessage, PresencePriority, activitymap
from subsystems.timers import Timer
from data import Storage, Lang
from botutils.converters import get_best_user, get_best_username as gbu


class PresenceState:
    """
    Represents the current state the presence message was in the last time the updater coro ran.
    """
    def __init__(self, lfm_presence_msg):
        self.presence_msg = lfm_presence_msg
        self.timer: Optional[Timer] = None
        self.cur_listener_dc = None
        self.cur_listener_lfm = None
        self.cur_song = None
        self.cur_song_f = None

    def format_song(self):
        """
        Formats the current song according to plugin config settings and stores the result in self.cur_song_f.
        """
        plugin = self.presence_msg.plugin

        if plugin.get_config("presence_artist_only"):
            self.cur_song_f = self.cur_song.artist
        elif plugin.get_config("presence_title_only"):
            self.cur_song_f = self.cur_song.title
        elif plugin.get_config("presence_artist_and_title"):
            if plugin.get_config("presence_order_artist_title"):
                s0 = self.cur_song.artist
                s2 = self.cur_song.title
            else:
                s0 = self.cur_song.title
                s2 = self.cur_song.artist
            self.cur_song_f = " ".join((s0, Lang.lang(plugin, "by"), s2))
        else:
            assert False

        if plugin.get_config("presence_include_listener"):
            s1 = " ".join((Lang.lang(plugin, "with"), gbu(self.cur_listener_dc)))
            if plugin.get_config("presence_order_user_song"):
                s0 = s1
                s1 = self.cur_song_f
            else:
                s0 = self.cur_song_f
            self.cur_song_f = " ".join((s0, s1))

    async def reset(self):
        """
        Resets the state of the presence message, i.e. fetches a new random scrobble or skips the presence message
        if necessary

        :return: This PresenceState
        """
        rnd = await self.presence_msg.get_random_lastfm_listener()
        self.cur_listener_dc, self.cur_listener_lfm, self.cur_song = rnd
        if self.cur_song is not None:
            self.format_song()
        elif self.presence_msg.show_presence:
            await self.presence_msg.plugin.bot.presence.skip()
        return self

    def is_set(self) -> bool:
        return self.cur_listener_dc is not None


class LfmPresenceMessage(PresenceMessage):
    """
    Presence message that updates itself once every minute in case the listening song needs to change.
    """
    def __init__(self, lastfm):
        super().__init__(lastfm.bot, None, "DUMMY", PresencePriority.DEFAULT, activity="listening")

        self.logger = logging.getLogger(__name__)
        self.plugin = lastfm
        self.show_presence = self.plugin.show_presence  # keeps track of plugin cfg value
        if self.show_presence:
            self.register()

        self._activity_type = activitymap["listening"]

        # Handle us when we're up
        self.is_currently_shown = False
        self.state: Optional[PresenceState] = None

    async def set(self):
        """
        Is called by presence subsys to indicate that we are up
        """
        self.is_currently_shown = True
        await self.update()

    async def update(self):
        """
        Updates the currently shown presence is necessary. Sets a timer to repeat this every minute while this
        presence is up.
        :return:
        """
        if not self.is_currently_shown:
            return

        # first run, fill stuff
        first = False
        if self.state is None:
            first = True
            self.state = await PresenceState(self).reset()
            if not self.state.is_set():
                await self.bot.presence.skip()
                return

        if not first:
            song = await self.plugin.api.get_current_scrobble(self.state.cur_listener_lfm)
            if not song == self.state.cur_song:
                await self.state.reset()
                if not self.state.is_set():
                    await self.bot.presence.skip()
                    return

        self._activity = discord.Activity(type=self._activity_type, name=self.state.cur_song_f)
        await self.bot.change_presence(activity=self.activity_type)
        self.state.timer = Timer(self.bot, self.plugin.get_config("presence_tick"), self.update)

    async def unset(self):
        """
        Called by presence subsys once this presence message is not up anymore.
        """
        self.logger.debug("Lastfm presence message was unset")
        self.is_currently_shown = False
        if self.state is not None and self.state.timer is not None and not self.state.timer.has_run:
            self.state.timer.cancel()
        self.state = None

    async def get_random_lastfm_listener(self):
        """
        :return: Discord user, Lastfm user, song (can be None if nobody is listening)
        """
        users = Storage.get(self.plugin)["users"]
        candidates = list(users.keys())
        random.shuffle(candidates)

        for userid in candidates:
            lfmuser = users[userid]
            if lfmuser.get("presence_optout", not self.plugin.get_config("presence_optout")):
                self.logger.debug("Skipping user %s", lfmuser["lfmuser"])
                continue
            lfmuser = lfmuser["lfmuser"]

            song = await self.plugin.api.get_current_scrobble(lfmuser)
            if song:
                self.logger.debug("Got random listener %s: %s", lfmuser, song)
                return get_best_user(userid), lfmuser, song
        self.logger.debug("No random listener found")
        return None, None, None

    def register(self):
        self.logger.debug("Registering Lastfm presence")
        self.plugin.bot.presence.register_msg(self)

    def deregister(self):
        self.logger.debug("Deregistering Lastfm presence")
        super().deregister()

    def config_update(self):
        """
        Is called when the "presence" config key of the plugin is changed.
        """
        if self.plugin.show_presence and not self.show_presence:
            self.show_presence = True
            self.register()

        elif not self.plugin.show_presence and self.show_presence:
            self.show_presence = False
            self.deregister()
