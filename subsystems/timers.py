from copy import deepcopy
from calendar import monthrange
from threading import Thread
import datetime
import warnings

from discord.ext import tasks


timedictformat = ["month", "monthday", "weekday", "hour", "minute"]


class Mothership(Thread):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.timers = {}

    def fixjob(self, coro, **kwargs):
        """
        cron-like. Takes timedict elements as arguments.
        :param coro: Coroutine with the signature f(Cancellable).
        :param kwargs: Timedict + repeat.
        """
        # Argument validating
        for el in kwargs:
            if el not in timedictformat and el != "repeat":
                raise RuntimeError("Unknown argument: {}".format(el))

        repeat = True
        if "repeat" in kwargs:
            repeat = kwargs["repeat"]

        # Build timedict
        timedict = {}
        for el in timedictformat:
            if el in kwargs:
                timedict[el] = kwargs[el]
            else:
                timedict[el] = None

        # Actual timer registering logic
        td = normalize_td(timedict)
        dt = next_occurence(td)
        cancellable = Cancellable(self, kwargs)
        self.timers[cancellable] = coro

    

    def timer(self, coro, seconds):
        tasks.Loop(coro, seconds)

    def cancel(self, cancellable):
        try:
            del self.timers[cancellable]
        except KeyError as e:
            warnings.warn("Cancelled timer not found.")  # todo stacktrace


class Cancellable:
    def __init__(self, mothership, timedict):
        self.mothership = mothership
        self.data = None
        self._timedict = timedict
        self._cancelled = False

    @property
    def timedict(self):
        return deepcopy(self._timedict)

    @property
    def cancelled(self):
        return self._cancelled

    def cancel(self):
        self._cancelled = True
        self.mothership.cancel(self)


class Job:
    def __init__(self, mothership, timedict):
        self.mothership = mothership
        self.timedict = timedict
        self.next_task = None


def normalize_td(td):
    """
    Normalizes a timedict to consist of only lists. Also validates formats.
    :return: Normalized timedict;
    """
    ntd = {}
    for el in timedictformat:
        if el in td:
            # ghetto check for filled iterable
            if not td[el]:
                ntd[el] = None
                continue
            ntd[el] = td[el]
            try:
                for _ in td[el]:
                    break
            except TypeError:
                if not isinstance(td[el], int):
                    raise TypeError("Expecting an int or a list of ints as {}".format(el))
                ntd[el] = [td[el]]
        else:
            ntd[el] = None
    return ntd


def ringdistance(a, b, size):
    """
    Returns the smallest positive forward-distance between b and a in a ring of the form 1..size, e.g.:
    ringdistance(1, 3, 12) == 2   # january, march
    ringdistance(3, 1, 12) == 10  # march, january
    """
    if not 0 < b <= size or not 0 < a <= size:
        raise ValueError("Expecting {} and {} to be between 1 and {}".format(b, a, size))
    wraparound = size - a + b
    regular = b - a
    if wraparound < regular or regular < 0:
        return wraparound
    return regular


def nearest_element(me, haystack, ringsize):
    """
    Finds the element in haystack that is the closest to me in a forward-distance. Assumes a ring of ringsize.
    If haystack is None, returns me. Distance of 0 counts.
    """
    if haystack is None:
        return me

    r = haystack[0]
    last_distance = ringdistance(me, haystack[0], ringsize)
    for i in range(1, len(haystack)):
        d = ringdistance(me, haystack[i], ringsize)
        if d < last_distance:
            last_distance = d
            r = haystack[i]
    return r


def ring_iterator(haystack, startel, ringsize, startperiod):
    """
    Iterates forever over all elements in the ring elements in haystack. Starts counting at 1.
    :param haystack: The haystack with elements in the ring
    :param startel: haystack element to start the loop with
    :param ringsize: The size of the ring; assumes a ring of 1..ringsize
    :param startperiod: This value is iterated every cycle and returned as endperiod.
    :return: haystackelement, endperiod
    """
    print("Called ring_iterator({}, {}, {}, {})".format(haystack, startel, ringsize, startperiod))
    if haystack is None:
        haystack = [i for i in range(1, ringsize + 1)]

    i = None
    for k in range(len(haystack)):
        if haystack[k] == startel:
            i = k
    if i is None:
        raise RuntimeError("{} is not in haystack".format(startel))

    while True:
        if i >= len(haystack):
            i = 0
            startperiod += 1

        yield haystack[i], startperiod
        i += 1


def next_occurence(ntd):
    """
    Takes a normalized timedict and returns a datetime object that represents the next occurence of said timedict.
    """
    now = datetime.datetime.now()

    weekdays = ntd["weekday"]
    if not weekdays:
        weekdays = [i for i in range(1, 8)]

    # Find date
    date = None
    startday = now.day
    for month, year in ring_iterator(ntd["month"], now.month, 12, now.year):
        found = False
        for day in range(startday, monthrange(year, month)[1] + 1):
            if not datetime.date(year, month, day).weekday() + 1 in weekdays:
                print("no weekday {} in {}".format(datetime.date(year, month, day).weekday() + 1, weekdays))
                continue
            print(ntd["monthday"])
            if not ntd["monthday"] or day in ntd["monthday"]:

                # Find hour and minute
                starthour = 1
                startminute = 1
                thisday = True

                # Today
                if year == now.year and month == now.month and day == now.day:
                    starthour = now.hour
                    startminute = now.minute

                # find hour
                hour = None
                minute = None
                for hour, dayd in ring_iterator(ntd["hour"], starthour, 24, 0):
                    # wraparound
                    if dayd > 0:
                        thisday = False
                        break

                    minute = nearest_element(startminute, ntd["minute"], 60)
                    if minute < startminute:
                        startminute = 1
                        continue
                    break

                if thisday:
                    return datetime.datetime(year, month, day, hour, minute)

                # Continue loop
                found = True
                break
        if found:
            break
        startday = 1


@tasks.loop(seconds=5)
async def foo():
    pass
