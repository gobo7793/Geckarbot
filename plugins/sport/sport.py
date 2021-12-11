import logging

from base.configurable import BasePlugin, NotFound
from base.data import Config, Storage, Lang
from botutils.utils import helpstring_helper
from plugins.sport._scores import _Scores
from plugins.sport._liveticker import _Liveticker
from plugins.sport._predgame import _Predgame
from services import timers
from services.helpsys import DefaultCategories
from services.liveticker import LTSource, lt_source_links

logger = logging.getLogger(__name__)


class Plugin(BasePlugin, _Liveticker, _Predgame, _Scores, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self):
        self.bot = Config().bot
        BasePlugin.__init__(self)
        _Scores.__init__(self, self.bot)
        _Predgame.__init__(self, self.bot)
        _Liveticker.__init__(self, self.bot, self.get_name, self._get_predictions)
        self.bot.register(self, category=DefaultCategories.SPORT)
        self._update_config()

        self.today_timer = self.bot.timers.schedule(coro=self._today_coro, td=timers.timedict(hour=1, minute=0))

    def default_config(self, container=None):
        return {
            'cfg_version': 4,
            'sport_chan': 0,
            'league_aliases': {"bl": ["ger.1", "espn"]},
            'liveticker': {
                'interval': 15,
                'leagues': {"oldb": [], "espn": []},
                'do_intermediate_updates': True,
                'tracked_events': ['GOAL', 'YELLOWCARD', 'REDCARD']
            },
            'predgame': {
                'show_today_matches': True,
                'pinglist': [],
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
        if command.qualified_name in ("table", "fußball", "liveticker add", "liveticker del"):
            try:
                desc = helpstring_helper(self, command, "desc")
            except NotFound:
                desc = helpstring_helper(self, command, "help")
            sources = "\n".join(["  {} ({})".format(e.value, lt_source_links[e]) for e in LTSource])
            return f"{desc}\n{Lang.lang(self, 'available_sources', sources)}"
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
            logger.info("Updated config to version 1")

        if Config().get(self).get('cfg_version', 0) < 2:
            leagues = Config().get(self)['leagues']
            league_aliases = {}
            for k, aliases in leagues.items():
                for v in aliases:
                    league_aliases[v] = [k, "oldb"]
            Config().get(self)['league_aliases'] = league_aliases
            del Config().get(self)['leagues']
            Config().get(self)['cfg_version'] = 2
            logger.info("Updated config to version 2")

        if Config().get(self).get('cfg_version', 0) < 3:
            Config.get(self)["liveticker"]["show_today_matches"] = True
            Config.get(self)["liveticker"]["interval"] = 15
            Config.get(self)["predictions_overview_sheet"] = ""
            Storage.set(self, Storage.get_default(self))
            Config().get(self)['cfg_version'] = 3
            logger.info("Updated config to version 3")

        if Config().get(self).get('cfg_version', 0) < 4:
            Config.get(self)["predgame"] = {
                "show_today_matches": Config.get(self)["liveticker"]["show_today_matches"],
                "pinglist": []
            }
            del Config.get(self)["liveticker"]["show_today_matches"]
            Config().get(self)['cfg_version'] = 4
            logger.info("Updated config to version 4")

        Storage.save(self)
        Config().save(self)
