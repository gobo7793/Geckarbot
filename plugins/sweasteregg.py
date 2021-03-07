import asyncio
from datetime import date, timedelta
from typing import List, Optional

from base import BasePlugin
from conf import Config, Storage
from subsystems.presence import PresenceMessage, PresencePriority
from subsystems.timers import Job, timedict


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.MISC)

        self.presences = []  # type: List[PresenceMessage]
        self.orga_timer = None  # type: Optional[Job]
        self.meme_timer = None  # type: Optional[Job]
        self.channel = self.bot.guild.get_channel(Config.get(self)["channel_id"])

        if Config.get(self)["is_running"]:
            asyncio.run_coroutine_threadsafe(self._start(), self.bot.loop)
        else:
            self._prepare()

    def default_config(self):
        return {
            "version": 1,
            "mtimer_min": 60,  # in minutes per hour
            "channel_id": 0,
            "month": 5,
            "monthday": 4,
            # ints of storage IDs of the memes
            "meme_order": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
            "last_meme_index": -1,  # index of the last showed meme in meme_order
            "is_running": False
        }

    def default_storage(self):
        return {
            "memes": {
                0: "https://tenor.com/view/day-long-remembered-darth-vader-grand-moff-tarkin-tarkin-vader-gif-16214689",
                1: "https://tenor.com/view/hello-there-gif-9442662",
                2: "https://tenor.com/view/general-kenobi-kenobi-general-hello-there-star-wars-gif-13723705",
                3: "https://tenor.com/view/your-move-obi-wan-kenobi-star-wars-jedi-master-gif-15824683",
                4: "https://i.redd.it/aozydy26hki61.jpg",
                5: "https://cdn.discordapp.com/attachments/706129811382337566/818086156679118858/FB_IMG_1615117281039.jpg",
                6: "",
                7: "https://i.redd.it/84gafcvrjcl61.png",
                8: "",
                9: "https://i.redd.it/zf3b2i3y4hi61.jpg",
                10: "",
                11: "",
                12: "",
                13: "https://i.redd.it/003i3tinfel61.jpg",
                14: "",
                15: "",
                16: "https://tenor.com/view/impeachment-love-democracy-ilove-democracy-gif-15723806",
                17: "",
                18: "",
                19: "",
                20: "",
                21: "https://i.redd.it/a520dfy1bbl61.png",
                22: "",
                23: "https://tenor.com/view/general-grievous-abandon-ship-funny-abort-evacuate-gif-10721574",
            }
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
                    "with the Force",
                    "Emperor"
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
                    "mit der Macht",
                    "Imperator"
                ]
            }
        }

    def _prepare(self):
        """Prepares the easteregg"""
        month = Config.get(self)["month"]
        monthday = Config.get(self)["monthday"]
        start_date = date(year=date.today().year, month=month, day=monthday) - timedelta(days=1)
        otd = timedict(year=start_date.year, month=start_date.month, monthday=start_date.day,
                       hour=23, minute=30)
        self.orga_timer = self.bot.timers.schedule(self._stop, otd, repeat=False)
        Config.get(self)["last_meme_index"] = -1

    async def _start(self, job=None):
        """Starts the easteregg"""
        month = Config.get(self)["month"]
        monthday = Config.get(self)["monthday"]

        presence_strings = self.get_lang().get(self.bot.LANGUAGE_CODE, "en")["presences"]
        for presence_str in presence_strings:
            self.presences.append(self.bot.presence.register(presence_str, PresencePriority.HIGH))
        mtd = timedict(year=date.today().year, month=month, monthday=monthday,
                       minute=[i for i in range(0, 60, Config.get(self)["mtimer_min"])])
        self.meme_timer = self.bot.timers.schedule(self._mtimer_callback, mtd, repeat=True)

        finish_date = date(year=date.today().year, month=month, day=monthday) + timedelta(days=1)
        otd = timedict(year=finish_date.year, month=finish_date.month, monthday=finish_date.day)
        self.orga_timer = self.bot.timers.schedule(self._stop, otd, repeat=False)

        Config.get(self)["is_running"] = True
        Config.save(self)

    async def _stop(self, job):
        """Stops the easteregg"""
        for presence in self.presences:
            presence.deregister()

        Config.get(self)["is_running"] = False
        Config.save(self)

    async def _mtimer_callback(self, job):
        """The callback for the meme_timer"""
        if self.channel is None:
            return
        Config.get(self)["last_meme_index"] += 1
        self.channel.send(Storage.get(self)["memes"][Config.get(self)["last_meme_index"]])
