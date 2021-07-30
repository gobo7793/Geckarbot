import logging

from base import BasePlugin
from botutils.utils import helpstring_helper
from data import Config, Storage
from plugins.sport._livescores import _Livescores
from plugins.sport._liveticker import _Liveticker
from plugins.sport._predgame import _Predgame
from subsystems import timers
from subsystems.helpsys import DefaultCategories


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
            'cfg_version': 3,
            'sport_chan': 0,
            'league_aliases': {"bl": ["ger.1", "espn"]},
            'liveticker': {
                'interval': 15,
                'show_today_matches': True,
                'leagues': {"oldb": [], "espn": []},
                'do_intermediate_updates': True,
                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']
            },
            'predictions_overview_sheet': ''
        }

    def default_storage(self, container=None):
        return {
            "predictions": {
                # "ger.2": {  # espn_code
                #     "name": "2. Bundesliga"  # display name
                #     "sheet": "1nK92I12U8SLMsXRFTWJjweQDGTIYiL74MoFTQ3uXHZE",
                #     "name_range": "G1:AD1"  # sheets range in which the names are
                #     "points_range": "G4:AD4"  # sheets range in which the final total points are
                #     "prediction_range": "A6:AD354"  # sheets range in which the matchday prediction data are
                # }
            }
        }

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

        if Config().get(self).get('cfg_version', 0) < 3:
            Config.get(self)["liveticker"]["show_today_matches"] = True
            Config.get(self)["predictions_overview_sheet"] = ""
            Storage.set(self, Storage.get_default(self))
            Config().get(self)['cfg_version'] = 3
            self.logger.debug("Updated config to version 3")

        Storage.save(self)
        Config().save(self)
