from datetime import date
from typing import List, Optional

from discord import TextChannel
from discord.ext import commands

from base import BasePlugin, NotFound
from botutils.utils import add_reaction
from data import Config, Storage, Lang
from subsystems import helpsys
from subsystems.presence import PresenceMessage, PresencePriority
from subsystems.timers import Job, timedict


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, helpsys.DefaultCategories.MISC)

        self.presences = []  # type: List[PresenceMessage]
        self.orga_timer = None  # type: Optional[Job]
        self.meme_timer = None  # type: Optional[Job]
        self.channel = self.bot.guild.get_channel(Config.get(self)["channel_id"])

        if Config.get(self)["is_running"]:
            self.bot.loop.create_task(self._start())
        else:
            self._prepare()

    def default_config(self):
        return {
            "version": 1,
            "mtimer_min": 60,  # in minutes per hour
            "channel_id": 0,
            # ints of storage IDs of the memes
            "meme_order": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
            "last_meme_index": -1,  # index of the last showed meme in meme_order
            "is_running": False
        }

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
        return {
            "memes": {
                0: "https://tenor.com/view/day-long-remembered-darth-vader-grand-moff-tarkin-tarkin-vader-gif-16214689",
                1: "https://tenor.com/view/hello-there-gif-9442662",
                2: "https://tenor.com/view/general-kenobi-kenobi-general-hello-there-star-wars-gif-13723705",
                3: "https://tenor.com/view/your-move-obi-wan-kenobi-star-wars-jedi-master-gif-15824683",
                4: "https://i.redd.it/aozydy26hki61.jpg",
                5: "https://cdn.discordapp.com/attachments/706129811382337566/818086156679118858/"
                   "FB_IMG_1615117281039.jpg",
                6: "https://i.redd.it/pw7vxwklacw61.jpg",
                7: "https://i.redd.it/84gafcvrjcl61.png",
                8: "https://i.redd.it/i3mf352g8yt61.jpg",
                9: "https://i.redd.it/zf3b2i3y4hi61.jpg",
                10: "https://i.redd.it/xdn68eew6bw61.jpg",
                11: "https://i.imgur.com/P7q17T5.jpg",
                12: "https://cdn.shopify.com/s/files/1/1140/8354/files/star-wars-meme-15_480x480.jpg?v=1613780820",
                13: "https://i.redd.it/003i3tinfel61.jpg",
                14: "https://i.redd.it/hws8hk04f8v61.png",
                15: "https://i.redd.it/d9d4pophqdw61.jpg",
                16: "https://tenor.com/view/impeachment-love-democracy-ilove-democracy-gif-15723806",
                17: "https://i.redd.it/1y4r8a3bm4w61.jpg",
                18: "https://cdn.discordapp.com/attachments/337680937770942466/820358789533270076/"
                    "FB_IMG_1615659157536.jpg",
                19: "https://i.redd.it/3s41lcn2kso61.jpg",
                20: "https://i.redd.it/956q8wjgfcw61.jpg",
                21: "https://i.redd.it/dstj3k4646u61.jpg",
                22: "https://i.redd.it/29uk0r6nx9w61.jpg",
                23: "https://tenor.com/view/general-grievous-abandon-ship-funny-abort-evacuate-gif-10721574"
            }
        }

    def get_lang(self):
        return {
            "en_US": {
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
            "de_DE": {
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

    @commands.command(name="swe_channel", hidden=True, help="Sets the channel for the SW Easteregg")
    @commands.has_any_role(Config().MOD_ROLES)
    async def cmd_set_channel(self, ctx, channel: TextChannel):
        Config.get(self)["channel_id"] = channel.id
        Config.save(self)
        Storage.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="swe_stop", hidden=True, help="Stops the SW Easteregg")
    @commands.has_any_role(Config().MOD_ROLES)
    async def cmd_stop(self, ctx):
        if self.orga_timer is not None:
            self.orga_timer.cancel()
        if self.meme_timer is not None:
            self.meme_timer.cancel()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    def _prepare(self):
        """Prepares the easteregg"""
        start_date = date(year=date.today().year, month=5, day=3)
        otd = timedict(year=start_date.year, month=start_date.month, monthday=start_date.day,
                       hour=23, minute=0)
        self.orga_timer = self.bot.timers.schedule(self._start, otd, repeat=False)
        Config.get(self)["last_meme_index"] = -1

    async def _start(self, _job=None):
        """Starts the easteregg"""
        month = 5
        monthday = 4

        presence_strings = self.get_lang().get(self.bot.LANGUAGE_CODE, "en_US")["presences"]
        for presence_str in presence_strings:
            self.presences.append(self.bot.presence.register(presence_str, PresencePriority.HIGH))
        mtd = timedict(year=date.today().year, month=month, monthday=monthday,
                       minute=list(range(0, 60, Config.get(self)["mtimer_min"])))
        self.meme_timer = self.bot.timers.schedule(self._mtimer_callback, mtd, repeat=True)

        otd = timedict(year=date.today().year, month=month, monthday=monthday, hour=13, minute=30)
        self.orga_timer = self.bot.timers.schedule(self._stop, otd, repeat=False)

        self.channel = self.bot.guild.get_channel(Config.get(self)["channel_id"])

        Config.get(self)["is_running"] = True
        Config.save(self)

    async def _stop(self, _job):
        """Stops the easteregg"""
        for presence in self.presences:
            presence.deregister()

        Config.get(self)["is_running"] = False
        Config.save(self)

    async def _mtimer_callback(self, _job):
        """The callback for the meme_timer"""
        if self.channel is None:
            return
        Config.get(self)["last_meme_index"] += 1
        if Config.get(self)["last_meme_index"] >= len(Storage.get(self)["memes"]):
            Config.get(self)["last_meme_index"] = 0
        await self.channel.send(Storage.get(self)["memes"][Config.get(self)["last_meme_index"]])
        Config.save(self)
