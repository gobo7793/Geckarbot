from typing import List

from base import BasePlugin
from subsystems.presence import PresenceMessage, PresencePriority


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.MISC)

        self.presences = []  # type: List[PresenceMessage]

    def default_config(self):
        return {
            "version": 1,
            "meme_timer": 60,  # in minutes
            "channel_id": 0,
            "month": 5,
            "monthday": 4
        }

    def default_storage(self):
        return {
            "memes": [
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
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
                    "with his Death Star"
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
                    "mit seinem Todesstern"
                ]
            }
        }

    def _prepare_easteregg(self):
        presence_strings = self.get_lang().get(self.bot.LANGUAGE_CODE, "en")["presences"]
        for presence_str in presence_strings:
            self.presences.append(self.bot.presence.register(presence_str, PresencePriority.HIGH))

    def _stop_easteregg(self):
        for presence in self.presences:
            presence.deregister()
