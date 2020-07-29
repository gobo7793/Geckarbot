import logging
import warnings
import asyncio


class StateMachine:
    """
    Statemachine implementation for coroutines.
    """
    def __init__(self, verbose=True):
        self.msg = "statemachine " + str(id(self)) + ": "
        self.verbose = verbose
        self.states = {}
        self.start = None
        self.ends = []
        self._state = None
        self.has_ended = False
        self.logger = logging.getLogger(__name__)

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, state):
        if self.has_ended:
            self.logger.debug("{} state change to {} was requested but statemachine has already stopped at {}."
                              .format(self.msg, state, self._state))
            return
        if state not in self.states:
            raise Exception("unknown state: {}".format(state))

        if state == self._state:
            self.logger.debug("{} state is already {}; nothing to be done.".format(self.msg, state))
            return

        # Execute callback coro
        source = self._state
        coro, edges = self.states[state]
        if edges is not None and source not in edges:
            raise RuntimeError("{} {} -> {} is not an allowed transition.".format(self.msg, source, state))

        self.logger.debug("Setting state {}".format(state))
        self._state = state
        if state in self.ends:
            self.has_ended = True
        if coro is not None:
            self.logger.debug("Running coro for state {}".format(state))
            asyncio.create_task(coro())  # todo allow both coro() and coro

    def add_state(self, state, coro, allowed_sources=None, end=False):
        """
        Adds a state.
        :param state: Any object. Used as an identifier of the state that is set. If a state was already registered
        before, this throws a warning.
        :param coro: Coroutine that is called. Can be None if nothing should happen when reaching this state.
        A coroutine (or some other external force) is expected to change the statemachine's state on its own, it will
        not happen automatically.
        :param allowed_sources: List of states that are allowed to lead to this one (basically automaton edges).
        Raises RuntimeError if this is violated. If None, sources are ignored.
        :param end: If True, this is registered as an end state. If an end state is reached, the statemachine stops,
        the coro registered with this state is scheduled and future state changes are ignored.
        """
        if state in self.states:
            warnings.warn(RuntimeWarning("Statemachine: State added more than once: {}".format(state)))
        if self.verbose:
            self.logger.debug("{} state added: {}; handler: {}".format(self.msg, state, coro))
        if end:
            self.ends.append(state)

        self.states[state] = coro, allowed_sources
