from copy import deepcopy
import datetime


class Mothership:
    def __init__(self, bot):
        self.bot = bot


class Cancellable:
    def __init__(self, mothership, timedict):
        self.mothership = mothership
        self.data = None
        self._timedict = timedict

    @property
    def timedict(self):
        return deepcopy(self._timedict)

    def cancel(self):
        self.mothership.cancel(self)


def td_to_dt(td):
    """
    Converts a timedict into a datetime object.
    """
    pass


def fixjob(coro, **kwargs):
    """
    cron-like. Takes timedict elements as arguments.
    :param coro: Coroutine with the signature f(Cancellable).
    :param kwargs: Timedict + repeat.
    """
    args = {
        "month": None,
        "monthday": None,
        "weekday": None,
        "hour": None,
        "minute": None,
        "repeat": True,
    }


def timer(coro, seconds):
    pass
