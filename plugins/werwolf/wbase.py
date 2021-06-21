from enum import Enum


class Phase(Enum):
    # night
    PRENIGHT = 0  # notify everyone that a new turn has begun
    PREKILL = 1  # first things first
    KILL = 2  # witches and werewolves kill ppl
    INTERVENTION = 3  # saviours save ppl
    POSTKILL = 4  # on-death events
    WINCHECK = 5  # ppl have died, check if anyone has won the game
    POSTNIGHT = 6  # notify everyone that the night is over

    # day
    MAYOR = 7  # mayor election (if necessary)
    DISCUSSION = 8  # give ppl time to discuss what happened during the night
    VOTE = 9  # vote on who to kill


class BaseRoleController:
    def __init__(self, controller):
        self.controller = controller
        self.participants = []

    def add_participant(self, participant):
        pass

    # phases
    async def prenight_phase(self):
        pass

    async def prekill_phase(self):
        pass

    async def kill_phase(self):
        pass

    async def intervention_phase(self, victims):
        pass

    async def postkill_phase(self):
        pass

    async def wincheck_phase(self):
        pass

    async def postnight_phase(self):
        pass
