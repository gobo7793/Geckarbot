from botutils.statemachine import StateMachine

from wbase import Phase


class Death:
    def __init__(self, killer, victim):
        pass

    def revive(self):
        # called on intervention
        pass


class Controller:
    def __init__(self, config, participants, interface, gamelog):
        """
        Builds game structure (e.g. roles) and does the game loop

        :param config: Game configuration
        :param participants: List of participants
        :param interface: Interface
        :param gamelog: GameLog
        """
        self.config = config
        self.participants = participants
        self.interface = interface
        self.gamelog = gamelog
        self.role_controllers = []
        # TODO build role controllers

        self.statemachine = StateMachine()
        self.statemachine.add_state(Phase.PRENIGHT, self.prenight_phase, allowed_sources=[Phase.VOTE], start=True)
        self.statemachine.add_state(Phase.PREKILL, self.prekill_phase, allowed_sources=[Phase.PRENIGHT])
        # ... etc

    async def run(self):
        await self.statemachine.run()

    # Transitions / phases
    def prenight_phase(self):
        for cntr in self.role_controllers:
            await cntr.prenight_phase()

    def prekill_phase(self):
        for cntr in self.role_controllers:
            await cntr.prekill_phase()

    # ... etc

    # API for role controllers
    async def kill(self, source, target):
        pass

    async def intervene(self, source, target):
        # aka revive
        pass

    async def assign_role(self, target, role_cntr):
        pass

    async def delete_role(self, target, role_cntr):
        # takes away a role; maybe move this into assign_role
        pass
