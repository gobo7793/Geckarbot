import random

from plugins.wordle.game import HelpingSolver, Game, Guess, Correctness


class DiceSolver(HelpingSolver):
    def __init__(self, game: Game):
        self.game = game

    def get_guess(self) -> str:
        return random.choice(self.game.wordlist.words)

    def guess(self, word: str) -> Guess:
        return self.game.guess(word)

    def solve(self):
        while True:
            self.guess(self.get_guess())
            if self.game.done != Correctness.PARTIALLY:
                break
