import string
import random
import logging
from enum import Enum

import discord

from conf import Config

from plugins.quiz.utils import get_best_username


class InvalidAnswer(Exception):
    pass


class Difficulty(Enum):
    ANY = "any"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @staticmethod
    def human_readable(el):
        if el == Difficulty.ANY:
            return "Any"
        if el == Difficulty.EASY:
            return "Easy"
        if el == Difficulty.MEDIUM:
            return "Medium"
        if el == Difficulty.HARD:
            return "Hard"


class Score:
    def __init__(self, plugin, config, question_count):
        self._score = {}
        self._points = {}
        self.plugin = plugin
        self.config = config
        self.question_count = question_count
        self.answered_questions = []

        self.interpol_x = [0, 10, 35, 55, 75, 100]
        self.interpol_y = [0, 30, 60, 75, 88, 100]
        self.dd = self.divdiff(self.interpol_x, self.interpol_y)

    @staticmethod
    def divdiff(x, f):
        r = []
        for _ in range(len(x)):
            r.append([0] * len(x))
        for i in range(len(r)):
            for k in range(len(r)):
                # first column
                if i == 0:
                    r[i][k] = f[k]
                    continue
                # 0-triangle
                if i + k >= len(r):
                    continue
                a = r[i - 1][k + 1] - r[i - 1][k]
                b = x[k + i] - x[k]
                r[i][k] = a / b

        return r

    def f(self, a):
        """
        Function that is applied to every calculated score to improve the spread.
        :param a: Score value to be improved
        :return: Value between 0 and 100
        """
        r = self.dd[len(self.dd) - 1][0]
        for i in range(len(self.interpol_x) - 2, -1, -1):
            r = r * (a - self.interpol_x[i]) + self.dd[i][0]
        return r

    def calc_points(self, user):
        """
        :param user: The user whose points are to be calculated
        :return: user's points
        """
        if user not in self._score:
            raise KeyError("User {} not found in score".format(user))

        return int(round(self.f(100 * self._points[user] * (1 - 1/len(self.answered_questions)))))

    def points(self):
        """
        :return: A dict that contains the points of all participants.
        """
        r = {}
        for el in self._score:
            r[el] = self.calc_points(el)
        return r

    @property
    def score(self):
        return self._score.copy()

    def ladder(self, sort_by_points=False):
        """
        :return: List of members in score, sorted by score or points, depending on sort_by_points
        """
        firstsort = self._score
        secondsort = self.points()
        if sort_by_points:
            firstsort = secondsort
            secondsort = self._score

        # two-step sorting
        s = {}
        for user in firstsort:
            if firstsort[user] in s:
                s[firstsort[user]].append(user)
            else:
                s[firstsort[user]] = [user]
        for score in s:
            s[score] = sorted(s[score], key=lambda x: secondsort[x], reverse=True)
        keys = sorted(s.keys(), reverse=True)

        # flatten
        r = []
        for key in keys:
            for user in s[key]:
                r.append(user)
        return r

    def winners(self):
        """
        :return: Return list of winners
        """
        r = []
        lastscore = None
        for el in self.ladder():
            if self._score[el] == 0:
                break
            elif lastscore is None:
                r.append(el)
                lastscore = self._score[el]
            elif lastscore == self._score[el]:
                r.append(el)
            elif lastscore > self._score[el]:
                break
            else:
                assert False
        return r

    def embed(self, end=False, sort_by_points=False):
        embed = discord.Embed(title=Config().lang(self.plugin, "results_title"))

        ladder = self.ladder(sort_by_points=sort_by_points)
        place = 0
        for i in range(len(ladder)):
            user = ladder[i]
            if i == 0 or self._score[user] < self._score[ladder[i - 1]]:
                place += 1

            # embed
            name = "**#{}** {}".format(place, get_best_username(Config().get(self.plugin), user))
            value = "Correct answers: {}".format(self._score[user])
            if len(self) > 1:
                value = "{}\nScore: {}".format(value, self.calc_points(user))
            embed.add_field(name=name, value=value)

            i += 1

        if len(ladder) == 0:
            if end:
                embed.add_field(name="Nobody has scored!", value=" ")
            else:
                embed.add_field(name="**#1** Geckarbot", value="I won! :)")

        return embed

    def increase(self, member, question, amount=1, totalcorr=1,):
        """
        Increases a participant's score by amount. Registers the participant if not present.
        :param member: Discord member
        :param amount: Amount to increase the member's score by; defaults to 1.
        :param totalcorr: Total amount of correct answers to the question
        :param question: Question object (to determine the amount of questions correctly answered)
        """
        # Increment user score
        if member not in self._score:
            self.add_participant(member)
        self._score[member] += amount
        self._points[member] += amount / totalcorr / self.question_count

        # Handle list of answered questions
        if question is not None:
            if self.answered_questions is None:
                self.answered_questions = [question]
            elif question not in self.answered_questions:
                self.answered_questions.append(question)

    def add_participant(self, member):
        if member not in self._score:
            self._score[member] = 0
            self._points[member] = 0
        else:
            logging.getLogger(__name__).warning("Adding {} to score who was already there. This should not happen.")

    def __len__(self):
        return len(self._score)


class Question:
    def __init__(self, question, correct_answer, incorrect_answers, index=None, info=None):
        logging.debug("Question({}, {}, {})".format(question, correct_answer, incorrect_answers))
        self.index = index
        self.info = info
        if info is None:
            self.info = {}

        self.question = question
        self.correct_answer = correct_answer
        self.incorrect_answers = incorrect_answers

        self.all_answers = incorrect_answers.copy()
        self.all_answers.append(correct_answer)
        random.shuffle(self.all_answers)

        self._cached_emoji = None
        self.message = None

        # Set emoji and letter format of correct answer
        self.correct_answer_emoji = None
        self.correct_answer_letter = None
        for i in range(len(self.all_answers)):
            if self.correct_answer == self.all_answers[i]:
                e = self.letter_mapping(i, emoji=True, reverse=False)
                letter = self.letter_mapping(i, emoji=False, reverse=False)
                self.correct_answer_emoji = "{} {}".format(e, self.correct_answer)
                self.correct_answer_letter = "**{}:** {}".format(letter, self.correct_answer)
                break

    def letter_mapping(self, index, emoji=False, reverse=False):
        if not reverse:
            if emoji:
                return self.emoji_map[index]
            else:
                return string.ascii_uppercase[index]

        # Reverse
        if emoji:
            haystack = self.emoji_map
        else:
            index = index.lower()
            haystack = string.ascii_lowercase

        for i in range(len(haystack)):
            if str(index) == str(haystack[i]):
                return i
        return None

    async def pose(self, channel, emoji=False):
        logging.getLogger(__name__).debug("Posing question #{}: {}".format(self.index, self.question))
        msg = await channel.send(embed=self.embed(emoji=emoji))
        if emoji:
            for i in range(len(self.all_answers)):
                await msg.add_reaction(Config().EMOJI["lettermap"][i])  # this breaks if there are more than 26 answers
        self.message = msg
        return msg

    def embed(self, emoji=False, info=False):
        """
        :param emoji: Determines whether A/B/C/D are letters or emoji
        :param info: Adds additional info to the embed such as category and difficulty
        :return: An embed representation of the question.
        """
        title = self.question
        if self.index is not None:
            title = "#{}: {}".format(self.index+1, title)
        embed = discord.Embed(title=title)
        value = "\n".join([el for el in self.answers_mc(emoji=emoji)])
        embed.add_field(name="Possible answers:", value=value)

        if info:
            for key in self.info:
                embed.add_field(name=key, value=str(self.info[key]))
        return embed

    def answers_mc(self, emoji=False):
        """
        :param emoji: If True, uses unicode emoji letters instead of regular uppercase letters
        :return: Generator for possible answers in a multiple-choice-fashion, e.g. "A: Jupiter"
        """
        for i in range(len(self.all_answers)):
            if emoji:
                letter = "{}".format(self.letter_mapping(i, emoji=emoji))
            else:
                letter = "**{}:**".format(self.letter_mapping(i, emoji=emoji))
            yield "{} {}".format(letter, self.all_answers[i])

    def check_answer(self, answer, emoji=False):
        """
        Called to check the answer to the most recent question that was retrieved via qet_question().
        :return: True if this is the first occurence of the correct answer, False otherwise
        """
        if answer is None:
            return False

        if not emoji:
            answer = answer.strip().lower()
        i = self.letter_mapping(answer, emoji=emoji, reverse=True)

        if i is None:
            raise InvalidAnswer()
        elif self.all_answers[i] == self.correct_answer:
            return True
        else:
            return False

    @property
    def emoji_map(self):
        if self._cached_emoji is None:
            self._cached_emoji = Config().EMOJI["lettermap"][:len(self.all_answers)]
        return self._cached_emoji

    def is_valid_emoji(self, emoji):
        for el in self.emoji_map:
            if el == emoji:
                return True
        return False
