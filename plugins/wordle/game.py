from string import ascii_lowercase
from enum import Enum
from typing import List, Optional, Tuple

from plugins.wordle.wordlist import WordList


WORDLENGTH = 5


class Correctness(Enum):
    CORRECT = 0
    PARTIALLY = 1
    INCORRECT = 2


class Guess:
    """
    Represents a single word that was guessed and its character correctness list.
    """
    def __init__(self, word: str, correctness: List[Correctness]):
        self.word = word
        self.correctness = correctness
        assert len(word) == len(correctness)

    @property
    def is_correct(self) -> bool:
        for el in self.correctness:
            if el != Correctness.CORRECT:
                return False
        return True


class Game:
    """
    Represents a wordle game.
    """
    def __init__(self, wordlist: WordList, word: str = None):
        self.MAXTRIES = 6

        self.wordlist = wordlist
        self.guesses: List[Guess] = []
        self.solution = word if word else wordlist.randomSolution()
        self.solved = False

    @property
    def done(self) -> Correctness:
        """
        :return: The state of the game: Correct for solved, Incorrect for done and not solved, Partially for ongoing.
        """
        if self.solved:
            return Correctness.CORRECT
        if len(self.guesses) >= self.MAXTRIES:
            return Correctness.INCORRECT
        return Correctness.PARTIALLY

    def alphabet(self, uppercase: bool = True) -> Tuple[List[str], List[str], List[str]]:
        """
        Returns three disjunctive lists of characters that indicate whether they were correct, partially or none of
        those in all guesses combined.

        :param uppercase: switch to set upper case
        :return: list of char lists: found, out, unused
        """
        found_l = []
        out_l = []
        unused_l = []
        alphabet = list(ascii_lowercase)
        for char in alphabet:
            found = False
            char_f = char.upper() if uppercase else char
            for guess in self.guesses:
                for i in range(WORDLENGTH):
                    if char != guess.word[i]:
                        continue

                    # char found; upgrade result
                    if guess.correctness[i] in (Correctness.CORRECT, Correctness.PARTIALLY):
                        found_l.append(char_f)
                        found = True
                        break
                    elif guess.correctness[i] == Correctness.INCORRECT:
                        out_l.append(char_f)
                        found = True
                        break
                if found:
                    break

            if not found:
                unused_l.append(char_f)

        return found_l, out_l, unused_l

    def guess(self, word: str) -> Guess:
        """
        Guesses a word.

        :param word: word to be guessed
        :return: corresponding Guess instance
        :raises RuntimeError: if the game is already over
        :raises TypeError: if the word is too short or too long
        :raises ValueError: if the word is not in the word list
        """
        if len(self.guesses) >= self.MAXTRIES:
            raise RuntimeError("maximum amount of guesses reached")
        if self.solved:
            raise RuntimeError("game is already solved")
        if len(word) != len(self.solution):
            raise TypeError("Word of length {} expected, got word of length {}".format(len(self.solution), len(word)))
        if word not in self.wordlist:
            raise ValueError("Word not in word list")

        correctness: List[Optional[Correctness]] = [None] * WORDLENGTH
        solution: List[Optional[str]] = list(self.solution)

        # first round: determine corrects
        for i in range(len(word)):
            if word[i] == solution[i]:
                correctness[i] = Correctness.CORRECT
                solution[i] = None

        # first round: determine partially corrects
        for i in range(len(correctness)):
            if correctness[i] is not None:
                continue

            if word[i] in solution:
                correctness[i] = Correctness.PARTIALLY
                solution[solution.index(word[i])] = None

        # third round: fill with incorrects
        for i in range(len(correctness)):
            if correctness[i] is None:
                correctness[i] = Correctness.INCORRECT

        r = Guess(word, correctness)
        self.guesses.append(r)
        if r.is_correct:
            self.solved = True
        return r
