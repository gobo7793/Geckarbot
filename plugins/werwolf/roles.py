from wbase import BaseRoleController


class Witch(BaseRoleController):
    def __init__(self, controller):
        super().__init__(controller)
        self.has_killed = False
        self.has_saved = False

    def kill_phase(self):
        # prompt to kill someone
        pass

    def intervention_phase(self, deaths):
        # prompt to save people who have died
        pass
