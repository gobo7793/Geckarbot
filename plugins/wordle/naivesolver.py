import logging
import random
from typing import Optional, Dict, List, Iterable, Tuple

from botutils.utils import execute_anything_sync, log_exception

from plugins.wordle.game import HelpingSolver, Game, WORDLENGTH, Correctness, Guess
from plugins.wordle.utils import OutOfOptions


class NaiveSolver(HelpingSolver):
    """
    Solver that tries to gather complete information about the final guess before committing.
    """
    def __init__(self, game: Game):
        super().__init__(game)
        self.logger = logging.getLogger(__name__)
        self.current_candidate_cache = None

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

        # amount of characters; character -> [amount, max]
        # max is True if we know that amount is definite
        self.amounts: Dict[str, List[int, bool]] = {}

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
        :raises OutOfOptions: If the list would be empty
        """
        if self.current_candidate_cache is not None:
            return self.current_candidate_cache

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
            # find word in guesses
            found = False
            for guess in self.game.guesses:
                if word == guess.word:
                    found = True
                    break
            if found:
                continue

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

            # sort out by amounts
            for char, amount in self.amounts.items():
                amount, definite = amount
                found = word.count(char)
                if definite and found != amount:
                    mismatch = True
                    break
                if not definite and found < amount:
                    mismatch = True
                    break
            if mismatch:
                continue

            # find floaters
            for i in unclear_indexes:
                if word[i] in floaters_found:
                    floaters_found[word[i]] = True

            found = True
            for floater in floaters_found.values():
                if not floater:
                    found = False
                    break
            if not found:
                continue

            r.append(word)

        if not r:
            # candidate list is empty, everybody panic
            e = OutOfOptions()
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

        self.current_candidate_cache = r
        self.digest_by_candidates()
        return r

    def found_count(self, char: str = None) -> int:
        """
        :param char: only count this char
        :return: The amount of found letters (Correctness.CORRECT)
        """
        r = 0
        for el in self.found:
            if el is not None and (char is None or char == el):
                r += 1
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

    def not_found_iter(self) -> Iterable[int]:
        """
        Iterator for the places that are not found yet
        :return: iterator with indexes
        """
        for i in range(WORDLENGTH):
            if self.found[i] is None:
                yield i

    def char_score(self) -> Dict[str, int]:
        """
        Calculates the kubb score of every char in possible.
        :return:
        """
        kubbscore = {}
        candidates = self.current_candidates()
        for char in self.possible:
            kubbscore[char] = 0
            for word in candidates:
                for i in self.not_found_iter():
                    if word[i] == char:
                        kubbscore[char] += 1
                        break
            # cut score by half
            if kubbscore[char] >= len(candidates) // 2:
                kubbscore[char] -= kubbscore[char] - len(candidates) // 2

        return kubbscore

    def kubb_score(self) -> Dict[str, int]:
        """
        Calculates scores for candidate words to determine how well they are equipped to divide
        the candidates list in half with the information it provides.

        :return: word scores
        """
        candidates = self.current_candidates()
        word_scores = {}
        for word in candidates:
            letter_scores: Dict[str, List[int]] = {}
            for i in self.not_found_iter():

                # word score: info score of this word
                letter_score = 0
                for j in range(len(candidates)):
                    kubb = candidates[j]
                    if word[i] == kubb[i]:
                        if letter_score >= len(candidates) // 2:
                            letter_score -= 1
                        else:
                            letter_score += 1

                if word[i] in letter_scores:
                    letter_scores[word[i]].append(letter_score)
                else:
                    letter_scores[word[i]] = [letter_score]

            # combine letter scores by factoring in amounts
            word_scores[word] = 0
            for char, scores in letter_scores.items():
                amount = 0 if char not in self.amounts else self.amounts[char][0]
                if len(scores) > amount:
                    word_scores[word] += sorted(scores)[0]

        return word_scores

    def info_score(self, word: str) -> int:
        """
        Calculates the amount of info a guess gives by assigning it a score.
        :param word: word to score
        :return: word score
        """
        so_far = []
        r = 0
        for i in range(WORDLENGTH):
            if word[i] == self.found[i]:
                r -= 1
                continue

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
                r -= 1
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
        self.current_candidate_cache = None
        partiallies = []

        # amounts prototype for this word, to be merged into self.amounts
        amounts: Dict[str, List[int, bool]] = {}
        for i in range(WORDLENGTH):
            char = guess.word[i]
            correctness = guess.correctness[i]
            if char not in amounts:
                amounts[char] = [0, False]

            if correctness == Correctness.CORRECT:
                amounts[char][0] += 1

                if not self.found[i]:
                    self.found[i] = char

                    # first occurence of this correct char; purge char from elsewhere lists
                    for sublist in self.elsewhere:
                        if char in sublist:
                            sublist.remove(char)
                else:
                    assert self.found[i] == char

            if correctness == Correctness.PARTIALLY:
                amounts[char][0] += 1

                partiallies.append(char)
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
                amounts[char][1] = True
            if correctness == Correctness.INCORRECT and char not in partiallies:
                if char in self.possible:
                    self.possible.remove(char)

                for sublist in self.candidates:
                    if char in sublist:
                        sublist.remove(char)

        # fish for lonely elsewheres that lead to a found
        change_done = True
        while change_done:
            change_done = False
            candidates = []
            for i in self.not_found_iter():
                pl = self.elsewhere[i]
                for char in pl:
                    if char not in candidates:
                        candidates.append(char)

            for char in candidates:
                candidate_i = None
                found = False
                for i in self.not_found_iter():
                    if char not in self.elsewhere[i]:
                        if candidate_i is None:
                            found = True
                            candidate_i = i
                        else:
                            found = False
                            break

                if found:
                    self.logger.debug("Deduced %s at %s because of elsewheres", char, candidate_i)
                    change_done = True
                    self.found[candidate_i] = char

        # update self.amounts
        for char, amount_t in amounts.items():
            # irrelevant
            if amount_t[0] == 0:
                continue

            if char not in self.amounts:
                self.amounts[char] = amount_t
                continue

            if amount_t[0] > self.amounts[char][0]:
                self.amounts[char][0] = amount_t[0]
            if amount_t[1]:
                self.amounts[char][1] = True

        self.logger.debug("Digested %s, amounts: %s, self.amounts: %s", guess.word, amounts, self.amounts)

    def digest_by_candidates(self):
        """
        Updates the possible list by removing characters that are not in candidates.
        """
        self.possible = []
        for word in self.current_candidates():
            for i in range(WORDLENGTH):
                if self.found[i] is None and word[i] not in self.possible:
                    self.possible.append(word[i])
        self.possible = sorted(self.possible)

    def get_kubb_word_guess(self) -> Tuple[str, int]:
        """
        Gets the word that (a) is an actual candidate and (b) gives the most information based on candidates
        :return: guess, score
        """
        kubbscore = self.kubb_score()
        best_score = None
        candidates = None
        for word, score in kubbscore.items():
            if best_score is None or score > best_score:
                best_score = score
                candidates = []
            if best_score == score:
                candidates.append(word)
        r = random.choice(candidates)
        self.logger.debug("Kubb guess: %s with a score of %s", r, best_score)
        return r, best_score

    def get_kubb_char_guess(self) -> Tuple[str, int]:
        """
        Gets the word that gives the most information based on candidates without necessarily being a candidate.
        :return: guess, score
        """
        charkubb = self.char_score()
        best_score = None
        candidates = None
        for word in self.game.wordlist.words:
            s = 0
            scored = []
            for char in word:
                # ignore if we already know the amount of this char
                if char in self.amounts and self.amounts[char][1]:
                    continue

                # ignore if there are not enough occurences of char
                if char in self.amounts and self.amounts[char][0] <= word.count(char):
                    continue

                # don't score the same char twice
                if char not in self.amounts and char in scored:
                    continue

                # otherwise, add score
                if char in charkubb and charkubb[char] > 0:
                    scored.append(char)
                    s += charkubb[char]
            if best_score is None or s > best_score:
                best_score = s
                candidates = [word]
            elif s == best_score:
                candidates.append(word)
        r = random.choice(candidates)
        self.logger.debug("Kubb char guess: %s with a score of %s", r, best_score)
        return r, best_score

    def get_best_kubb_guess(self):
        """
        :return: The better kubb guess between char and word kubb score.
        """
        char_guess, char_score = self.get_kubb_char_guess()
        word_guess, word_score = self.get_kubb_word_guess()
        if char_score > word_score:
            self.logger.debug("Kubb guess: char, %s with a score of %s", char_guess, char_score)
            return char_guess

        self.logger.debug("Kubb guess: word, %s with a score of %s", word_guess, word_score)
        return word_guess

    def get_guess(self) -> str:
        """
        Calculates the next guess.
        :return: Word that is to be guessed next
        """
        # Actual guess if enough info is gathered
        self.logger.debug("Guessing; found: %s", self.found_count())
        r = self.word_found()
        if r:
            self.logger.debug("complete guess: %s", r)

        # Panic mode, not enough guesses remain to be completely stable
        elif len(self.game.guesses) == self.game.max_tries - 1:
            r = self.best_guess()
            self.logger.debug("panic guess: %s", r)

        # Info guess
        else:
            # kubb guess
            if len(self.game.guesses) >= 2:
                r = self.get_best_kubb_guess()

            # Random info score guess
            else:
                scores = self.calc_scores()
                score = sorted(scores, reverse=True)[0]
                r = random.choice(scores[score])
                self.logger.debug("info guess: %s with score %s (out of %s candidates)",
                                  r, str(score), str(len(scores[score])))

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
