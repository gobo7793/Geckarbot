import logging
import inspect


class IllegalTransition(Exception):
    pass


async def execute_anything(f, *args, **kwargs):
    """
    Executes functions, coroutine functions and coroutines, returns their return values and raises their exceptions.
    :param f: Function, coroutine function or coroutine to execute / schedule
    :param args: args to pass to f
    :param kwargs: kwargs to pass to f
    :return: Return value of f
    """
    if inspect.iscoroutinefunction(f):
        f = f(*args, **kwargs)
    if inspect.iscoroutine(f):
        """
        loop = asyncio.get_event_loop()
        task = loop.create_task(f)
        loop.run_until_complete(task)
        e = task.exception()
        if e is not None:
            raise e
        return task.result()
        """
        return await f
    else:
        return f(*args, **kwargs)


class StateMachine:
    """
    Statemachine implementation for coroutines.
    """
    def __init__(self, init_state=None, verbose=True):
        self.msg = "statemachine " + str(id(self)) + ": "
        self.verbose = verbose
        self.states = {}
        self._is_running = False
        self.start = None
        self.ends = []
        self._init_state = init_state
        self._state = init_state
        self.has_ended = False
        self.cleanup = None
        self.logger = logging.getLogger(__name__)
        self._cancelled = False

    async def run(self):
        if self._is_running:
            raise RuntimeError("Statemachine is already running.")
        self._is_running = True
        self._cancelled = False

        # Execute
        to_call, _ = self.states[self.start]
        self._state = self.start
        init = True
        while True:
            # Execute
            source = self._state
            self._state = await execute_anything(to_call)
            self.logger.debug("Old state: {}".format(source))
            self.logger.debug("New state: {}".format(self._state))

            # Cancel
            if self._cancelled:
                self.end()
                break

            # End state
            if self._state is None:
                # At least one registered end state
                if self.ends:
                    if source in self.ends:
                        self.end()
                        break
                    else:
                        raise IllegalTransition("{} is not registered as an end state but did not return a new state"
                                                .format(source))
                # No end state registered
                else:
                    self.end()
                    break

            # Errors
            if self._state not in self.states:
                raise RuntimeError("Unknown state: {}".format(self._state))
            to_call, edges = self.states[self._state]
            if edges is not None and source not in edges and not (init and source is None):
                raise IllegalTransition("{} {} -> {} is not an allowed transition."
                                        .format(self.msg, source, self._state))
            init = False

    def end(self):
        self._is_running = False
        self._state = self._init_state

    @property
    def state(self):
        print("state: {}".format(self._state))
        return self._state

    def is_running(self):
        return self._is_running

    def cancelled(self):
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    def add_state(self, state, coro, allowed_sources=None, start=False, end=False):
        """
        Adds a state.
        :param state: Any object. Used as an identifier of the state that is set. If a state was already registered
        before, a warning is logged.
        :param coro: Coroutine that is called. Can be None if nothing should happen when reaching this state.
        A coroutine is expected to return the next state that the state machine is going to be in or None if the
        statemachine is going to be ended.
        :param allowed_sources: List of states that are allowed to lead to this one (represent automaton edges).
        Raises RuntimeError if this is violated. If None, sources are ignored.
        :param start: If True, this is registered as the state that the statemachine first transitions to.
        If no start state is registered, the statemachine cannot start. There can only be one start state.
        :param end: If True, this is registered as an end state. If at least one end state is registered and the
        statemachine ends on a non-end state, IllegalTransition is raised. If no end state is registered, this
        check is omitted.
        """
        if start:
            self.start = state
            if allowed_sources is not None:
                raise RuntimeError("The start state cannot have allowed_sources.")
            if coro is None:
                self.logger.warning("Start state defined without a callback")
        if state in self.states:
            self.logger.warning("Statemachine: State added more than once: {}".format(state))
        if self.verbose:
            self.logger.debug("{} state added: {}; handler: {}".format(self.msg, state, coro))
        if end:
            self.ends.append(state)

        self.states[state] = coro, allowed_sources

    def set_cleanup(self, coro):
        """
        Sets a cleanup coroutine that is called when an exception happens during state coro execution.
        After calling the cleanup coroutine, the exception will be raised further.
        :param coro: Awaitable coroutine with the signature `coro(exception)` with `exception` being the exception
        that cause the cleanup coro execution.
        """
        self.cleanup = coro
