from datetime import datetime, date, timedelta
from typing import List, Optional

from base import BasePlugin
from conf import Config
from subsystems.timers import Job, timedict
from subsystems.presence import PresenceMessage, PresencePriority


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.MISC)

        self.presences = []  # type: List[PresenceMessage]
        self.orga_timer = None  # type: Optional[Job]
        self.meme_timer = None  # type: Optional[Job]
        self.channel = self.bot.guild.get_channel(Config.get(self)["channel_id"])

    def default_config(self):
        return {
            "version": 1,
            "mtimer_min": 60,  # in minutes per hour
            "channel_id": 0,
            "month": 5,
            "monthday": 4,
            # ints of storage IDs of the memes
            "meme_order": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
            "last_meme_index": -1  # index of the last showed meme in meme_order
        }

    def default_storage(self):
        return {
            "memes": [
                "https://tenor.com/view/hello-there-gif-9442662",
                "https://tenor.com/view/general-kenobi-kenobi-general-hello-there-star-wars-gif-13723705",
                "",
                "",
                "",
                "",
                "",
                "https://i.redd.it/u4viabqenpi61.png",
                "https://i.redd.it/zf3b2i3y4hi61.jpg",
                "",
                "",
                "",
                "",
                "",
                "",
                "https://tenor.com/view/your-move-obi-wan-kenobi-star-wars-jedi-master-gif-15824683",
                "",
                "",
                "",
                "",
                "",
                "",
                "https://i.redd.it/aozydy26hki61.jpg",
                "https://tenor.com/view/general-grievous-abandon-ship-funny-abort-evacuate-gif-10721574",
            ]
        }

    def get_lang(self):
        return {
            "en": {
                "presences": [
                    "with his light saber",
                    "cleaning up the Jedi temple",
                    "with his imperial transporter",
                    "execution of Order 66",
                    "the Imperial March",
                    "with the Cantina Band",
                    "with his Death Star",
                    "with the Force"
                ]
            },
            "de": {
                "presences": [
                    "mit seinem Lichtschwert",
                    "Jedi-Tempel säubern",
                    "mit seinem imperialen Transporter",
                    "Ausführung der Order 66",
                    "den Imperial March",
                    "mit der Cantina Band",
                    "mit seinem Todesstern",
                    "mit der Macht"
                ]
            }
        }

    def _prepare_easteregg(self):
        """Prepares the easteregg"""
        pass

    async def _start_easteregg(self, job):
        """Starts the easteregg"""
        month = int(Config.get(self)["month"])
        monthday = int(Config.get(self)["monthday"])

        presence_strings = self.get_lang().get(self.bot.LANGUAGE_CODE, "en")["presences"]
        for presence_str in presence_strings:
            self.presences.append(self.bot.presence.register(presence_str, PresencePriority.HIGH))
        mtd = timedict(month=month, monthday=monthday,
                       minute=[i for i in range(0, 60, Config.get(self)["mtimer_min"])])
        self.meme_timer = self.bot.timers.schedule(self._mtimer_callback, mtd, repeat=True)

        finish_date = date(year=date.today().year, month=month, day=monthday) + timedelta(days=1)
        otd = timedict(year=finish_date.year, month=finish_date.month, monthday=finish_date.day)
        self.orga_timer = self.bot.timers.schedule(self._stop_easteregg, otd, repeat=False)

    async def _stop_easteregg(self, job):
        """Stops the easteregg"""
        for presence in self.presences:
            presence.deregister()
        self.meme_timer.cancel()

    async def _mtimer_callback(self, job):
        """The callback for the meme_timer"""
        if self.channel is None:
            return

