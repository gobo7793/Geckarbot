import asyncio
import calendar
import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient
from botutils.stringutils import paginate
from botutils.utils import add_reaction, helpstring_helper
from data import Lang, Config
from plugins.sport._livescores import _Livescores
from plugins.sport._liveticker import _Liveticker
from plugins.sport._predgame import _Predgame
from subsystems import timers
from subsystems.helpsys import DefaultCategories
from subsystems.liveticker import LivetickerKickoff, LivetickerUpdate, LivetickerFinish, LTSource, PlayerEventEnum, \
    Match, MatchStatus, TeamnameDict
from subsystems.reactions import ReactionAddedEvent


class Plugin(BasePlugin, _Liveticker, _Predgame, _Livescores, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category=DefaultCategories.SPORT)
        self.logger = logging.getLogger(__name__)
        self._update_config()

        self.today_timer = self.bot.timers.schedule(coro=self._today_coro, td=timers.timedict(hour=1, minute=0))

    def default_config(self):
        return {
            'cfg_version': 2,
            'sport_chan': 0,
            'league_aliases': {"bl": ["ger.1", "espn"]},
            'liveticker': {
                'leagues': {"oldb": [], "espn": []},
                'do_intermediate_updates': True,
                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']
            }
        }

    def default_storage(self, container=None):
        return []

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    async def shutdown(self):
        self.today_timer.cancel()

    def _update_config(self):
        if Config().get(self).get('cfg_version', 0) < 1:
            Config().get(self)['liveticker'] = {'leagues': Config().get(self)['liveticker_leagues'],
                                                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']}
            del Config().get(self)['liveticker_leagues']
            Config().get(self)['cfg_version'] = 1
            self.logger.debug("Updated config to version 1")
        if Config().get(self).get('cfg_version', 0) < 2:
            leagues = Config().get(self)['leagues']
            league_aliases = {}
            for k, aliases in leagues.items():
                for v in aliases:
                    league_aliases[v] = [k, "oldb"]
            Config().get(self)['league_aliases'] = league_aliases
            del Config().get(self)['leagues']
            Config().get(self)['cfg_version'] = 2
            self.logger.debug("Updated config to version 2")
        Config().save(self)
