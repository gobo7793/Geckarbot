import logging

from discord.ext import commands

from base import BasePlugin
from botutils.questionnaire import Question, Questionnaire, QuestionType


protoquestions = [
    ("Rasierst du dich nass oder trocken?", QuestionType.SINGLECHOICE, ["nass", "trocken", "gar nicht"]),
    ("Was für einen Rasierer hast du?", QuestionType.TEXT, None),
    ("Wo rasierst du dich?", QuestionType.MULTIPLECHOICE, ["spiegel", "dusche", "tram"])
]


class Plugin(BasePlugin):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)

        self.answers = []
        self.logger = logging.getLogger(__name__)

        self.bot.register(self)

    @commands.command(name="blub")
    async def poll(self, ctx):
        self.logger.debug("Caught poll cmd")
        questions = [Question(question, qtype, answers=answers) for question, qtype, answers in protoquestions]
        questionnaire = Questionnaire(self.bot, ctx.message.author, questions, "poll demo")

        try:
            answers = await questionnaire.interrogate()
            self.answers.append(answers)
        except (KeyError, RuntimeError):
            await ctx.send("Sorry, DM channel blocked")
            return

    @commands.command(name="results")
    async def results(self, ctx):
        for el in self.answers:
            msg = [element.answer for element in el]
            await ctx.send(str(msg))
