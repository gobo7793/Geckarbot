import random

from plugins.wordle.game import HelpingSolver, Game, Guess, Correctness


class DiceSolver(HelpingSolver):
    """
    Trivial example solver that randoms every guess
    """
    def __init__(self, game: Game):
        super().__init__(game)

    def get_guess(self) -> str:
        return random.choice(self.game.wordlist.words)

    def guess(self, word: str) -> Guess:
        return self.game.guess(word)

    def digest_guess(self, guess: Guess):
        pass

    def solve(self):
        while True:
            guess = self.game.guess(self.get_guess())
            self.digest_guess(guess)
            if self.game.done != Correctness.PARTIALLY:
                break
