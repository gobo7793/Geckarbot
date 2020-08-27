from datetime import datetime

from base import BasePlugin


class Question:
    def __init__(self):
        self.question = None
        self.answers = {}

    def add_answer(self, short, long):
        self.answers[short] = long


class Vote:
    def __init__(self):
        self.creator = None
        self.date = datetime.now()


class Poll:
    def __init__(self):
        self.name = None
        self.creator = None
        self.votes = []


class PollCreator:
    def __init__(self, user):
        self.user = user


class Plugin(BasePlugin):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        self.bot.register(self)

        self.polls = {}
