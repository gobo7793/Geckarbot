import logging
import warnings


class StateMachine:
    """
    Statemachine implementation for coroutines.
    """
    def __init__(self, endless=False, verbose=False):
        self.msg = "statemachine " + str(id(self)) + ": "
        self.verbose = verbose
        self.states = {}
        self.start = None
        self.ends = []
        self.state = None
        self.endless = endless
        self.logger = logging.getLogger(__name__)

    def add_state(self, state, coro, end=False):
        """
        Adds a state.
        :param state: Any object. Used as an identifier of the state that is set. If a state was already registered
        before, this throws a warning.
        :param coro: Coroutine that is called. Can be None if this is an end state and nothing should happen
        when reaching it.
        A coroutine is expected to be of the form f(statemachine) and it is expected to change the statemachine's
        state on its own. Unfortunately, coroutines can't return anything.
        :param end: If True, this is an end state.
        """
        if state in self.states:
            warnings.warn(RuntimeWarning("Statemachine: State added more than once: {}".format(state)))
        if self.verbose:
            self.logger.debug("{} state added: {}; handler: {}".format(self.msg, state, coro))

        self.states[state] = coro
        if end:
            self.ends.append(state)

    def set_start(self, state):
        """
        Sets the start state. Overwrites previously set start states.
        """
        if self.verbose:
            self.logger.debug("{} start state set: {}".format(self.msg, state))
        if state in self.states:
            self.start = state
        else:
            raise Exception("unknown state: {}".format(state))

    async def run(self, verbose=None):
        """
        Executes the statemachine.
        """
        if verbose is not None:
            self.verbose = verbose
        if self.verbose:
            self.logger.debug("{}: running statemachine".format(self.msg))

        if self.start is None:
            raise Exception("no start state given")
        if not self.endless and self.ends == []:
            raise Exception("no end state given")

        self.state = self.start

        while True:
            if self.verbose:
                self.logger.debug("{} state: {}".format(self.msg, self.state))
            await self.states[self.state](self)
            if self.state not in self.states:
                raise Exception("unknown state: {}".format(self.state))
            elif self.state in self.ends:
                if self.verbose:
                    self.logger.debug("{} end state reached: ".format(self.msg, self.state))

                # Calling end state coro
                if self.states[self.state] is not None:
                    await self.states[self.state]()
                break
