import logging
import random
from typing import Optional, Dict, List

from botutils.utils import execute_anything_sync, log_exception

from plugins.wordle.game import HelpingSolver, Game, WORDLENGTH, Correctness, Guess


class NaiveSolver(HelpingSolver):
    """
    Solver that tries to gather complete information about the final guess before committing.
    """
    def __init__(self, game: Game):
        self.game = game
        self.logger = logging.getLogger(__name__)

        # characters that are definitely found at this position
        self.found: list = [None] * WORDLENGTH

        # characters that are definitely in the word but not necessarily at this position (Correctness.PARTIALLY)
        self.candidates = []
        for _ in range(WORDLENGTH):
            self.candidates.append([])

        # characters that are in the word but definitely not at this position (Correctness.PARTIALLY)
        self.elsewhere = []
        for _ in range(WORDLENGTH):
            self.elsewhere.append([])

        # characters that are not definitely ruled out
        self.possible = list(self.game.wordlist.alphabet)

    def log_charlists(self, error=False):
        """
        Logs the character state lists as debug (unless `error` is True).
        """
        f = self.logger.error if error else self.logger.debug
        f("Char lists for %s, %s guesses so far:", self.game.solution, len(self.game.guesses))
        f("Found: %s", str(self.found))
        f("Candidates: %s", str(self.candidates))
        f("Elsewhere: %s", str(self.elsewhere))
        f("Possible: %s", str(self.possible))

    def current_candidates(self) -> List[str]:
        """
        :return: List of words that could be the solution with the current char lists
        :raises RuntimeError: If the list would be empty
        """
        # find amout of unclear positions and gather floaters
        unclear_indexes = []
        floaters = {}  # characters that were only found partially
        for i in range(WORDLENGTH):
            unclear_indexes.append(i)
            for char in self.elsewhere[i]:
                if char not in floaters:
                    floaters[char] = False

        # search words
        r = []
        for word in self.game.wordlist.words:
            floaters_found = floaters.copy()
            # simple constraints
            mismatch = False
            for i in range(WORDLENGTH):
                char = word[i]
                if (self.found[i] is not None and char != self.found[i]) \
                        or char in self.elsewhere[i] \
                        or (char not in self.possible and char not in self.found):
                    mismatch = True
                    break
            if mismatch:
                continue

            # find floaters
            for i in unclear_indexes:
                if word[i] in floaters_found:
                    floaters_found[word[i]] = True

            found = True
            for k, floater in floaters_found.items():
                if not floater:
                    found = False
                    break
            if not found:
                continue

            r.append(word)

        if not r:
            # candidate list is empty, everybody panic
            e = RuntimeError("Alg is incomplete")
            guesses = []
            for el in self.game.guesses:
                guesses.append(el.word)
            fields = {
                "Solution": "||{}||".format(self.game.solution),
                "Guesses:": "\n".join(guesses)
            }
            execute_anything_sync(log_exception(e, fields=fields, title=":x: Wordle: Naive solver error"))
            self.log_charlists(error=True)
            raise e
        return r

    def word_found(self) -> Optional[str]:
        """
        :return: Solution if it was found; None otherwise
        """
        # simple case; all characters found
        complete = True
        for el in self.found:
            if el is None:
                complete = False
        if complete:
            return "".join(self.found)

        candidates = self.current_candidates()
        if len(candidates) == 1:
            return candidates[0]
        return None

    def info_score(self, word: str) -> int:
        """
        Calculates the amount of info a guess gives by assigning it a score.
        :param word: word to score
        :return: word score
        """
        so_far = []
        r = 0
        for i in range(WORDLENGTH):
            # no further points for double letters
            if word[i] in so_far:
                continue

            # no points for elsewhere and found (redundant information)
            if word[i] in self.elsewhere[i] or word[i] == self.found[i]:
                continue

            # could be
            if word[i] in self.possible:
                r += 2
            if word[i] in self.candidates[i]:
                r += 1
            so_far.append(word[i])
        return r

    def calc_scores(self) -> Dict[int, List[str]]:
        """
        Calculates the info score for every word in the word list.
        :return: dict: score -> list(words)
        """
        r = {}
        for word in self.game.wordlist.words:
            score = self.info_score(word)
            if score in r:
                r[score].append(word)
            else:
                r[score] = [word]
        return r

    def best_guess(self) -> str:
        """
        :return: The best guess based on the current situation.
        """
        candidates = self.current_candidates()
        self.logger.debug("Best guess: randoming out of %s candidates", str(len(candidates)))
        return random.choice(candidates)

    def digest_guess(self, guess: Guess):
        """
        Updates the char lists with findings from `guess`.

        :param guess: Guess object to update the character lists with
        """
        for i in range(WORDLENGTH):
            char = guess.word[i]
            correctness = guess.correctness[i]
            if correctness == Correctness.CORRECT:
                if not self.found[i]:
                    self.found[i] = char

                    # first occurence of this correct char; purge char from elsewhere lists
                    for sublist in self.elsewhere:
                        if char in sublist:
                            sublist.remove(char)
                else:
                    assert self.found[i] == char

            if correctness == Correctness.PARTIALLY:
                # append char to elsewhere if we are sure that it was not found already
                if char not in self.elsewhere[i]:
                    elsewhere = True
                    for k in range(len(self.found)):
                        if self.found[k] != char or char == guess.word[k]:
                            continue
                        elsewhere = False
                        break
                    if elsewhere:
                        self.elsewhere[i].append(char)

                # add the character to all positions where it might be
                for j in range(WORDLENGTH):
                    if self.found[j] is not None:
                        continue
                    if i == j:
                        continue
                    if char in self.candidates[j]:
                        continue
                    if char in self.elsewhere[j]:
                        continue
                    self.candidates[j].append(char)

            if correctness == Correctness.INCORRECT:
                if char in self.possible:
                    self.possible.remove(char)

                for sublist in self.candidates:
                    if char in sublist:
                        sublist.remove(char)

    def get_guess(self) -> str:
        """
        Calculates the next guess.
        :return: Word that is to be guessed next
        """
        # Actual guess if enough info is gathered
        r = self.word_found()
        if r:
            self.logger.debug("complete guess: %s", r)

        # Panic mode, not enough guesses remain to be completely stable
        elif len(self.game.guesses) == self.game.max_tries - 1:
            r = self.best_guess()
            self.logger.debug("panic guess: %s", r)

        # Info guess
        else:
            scores = self.calc_scores()
            k = sorted(scores, reverse=True)[0]
            r = random.choice(scores[k])
            self.logger.debug("info guess: %s", r)

        return r

    def solve(self):
        """
        Solves a wordle by gathering as much info as possible about each character and delivering a final guess
        if all characters are set.
        """
        while True:
            self.log_charlists()
            guess = self.game.guess(self.get_guess())
            self.digest_guess(guess)
            if self.game.done != Correctness.PARTIALLY:
                break

        self.game.wordlist.invalidate_cache()
