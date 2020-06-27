from copy import deepcopy
from calendar import monthrange
from threading import Thread, Lock
from time import sleep
import sys
import asyncio
import logging
import warnings
import datetime


timedictformat = ["year", "month", "monthday", "weekday", "hour", "minute"]


class LastExecution(Exception):
    """
    Flow Control for non-repeating job execution
    """
    pass


class Mothership(Thread):
    def __init__(self, bot, launch_immediately=True):
        super().__init__()
        self.bot = bot
        self._jobs = []
        self._to_register = []
        self._lock = Lock()
        self._shutdown = False
        self.logger = logging.getLogger(__name__)

        if launch_immediately:
            self.start()

    def run(self):
        while True:
            if self._shutdown is not None:
                self.logger.info("Shutting down timer thread.")
                sys.exit(self._shutdown)
            with self._lock:
                self.logger.debug("Tick")
                # Handle registrations
                for el in self._to_register:
                    self.insert_job(el)
                self._to_register = []

                # Handle executions
                now = datetime.datetime.now()
                executed = []
                todel = []
                for el in self._jobs:
                    if (el.next_execution() - now).total_seconds() < 60:
                        try:
                            el.execute()
                            executed.append(el)
                        except LastExecution:
                            todel.append(el)
                    else:
                        break
                for el in executed:
                    self._jobs.remove(el)
                    self._to_register.append(el)
                for el in todel:
                    self._jobs.remove(el)

            tts = 60 - datetime.datetime.now().second + 1
            sleep(tts)

    def insert_job(self, job):
        """
        Inserts a job at the correct position in the job list.
        """
        nexto = job.next_execution()
        found = False
        for i in range(len(self._jobs)):
            if self._jobs[i].next_execution() > nexto:
                found = True
                self._jobs.insert(i, job)
                break
        if not found:
            self._jobs.append(job)

    def cancel(self, job):
        with self._lock:
            try:
                self._jobs.remove(job)
            except KeyError:
                warnings.warn("Cancelled job not found.")  # todo stacktrace

    def schedule(self, coro, td, repeat=True):
        """
        cron-like. Takes timedict elements as arguments.
        :param coro: Coroutine with the signature f(Cancellable).
        :param td: Timedict that specifies the execution schedule
        :param repeat: If set to False, the job runs only once.
        """
        job = Job(self, td, coro, repeat=repeat)
        self.logger.debug("Scheduling {}".format(job))
        self._to_register.append(job)
        return job

    def shutdown(self, exitcode):
        self.logger.debug("Thread shutdown has been requested.")
        self._shutdown = exitcode


class Job:
    def __init__(self, mothership, td, coro, repeat=True):
        self._mothership = mothership
        self._timedict = normalize_td(td)
        self._cancelled = False
        self._coro = coro
        self._repeat = repeat

        self.data = None

        self._cached_next_exec = next_occurence(self._timedict)
        self._last_exec = None

    @property
    def timedict(self):
        return deepcopy(self._timedict)

    @property
    def cancelled(self):
        return self._cancelled

    def cancel(self, lockless=False):
        self._mothership.logger.debug("Cancelling {}".format(self))
        self._cancelled = True
        if lockless:
            self._mothership.cancel(self)
        else:
            self._mothership.cancel_lockless(self)

    def execute(self):
        """
        Executes this job. Does not check if it is actually scheduled to be executed.
        """
        if self._last_exec is not None and (self.next_execution() - self._last_exec).total_seconds() < 60:
            warnings.warn("{}; {}: Job was about to be executed twice. THIS SHOULD NOT HAPPEN."
                          .format(self._last_exec, self._coro))
            return

        if self._cancelled:
            return

        self._mothership.logger.debug("Executing {} at {}".format(self, self.next_execution()))
        self._last_exec = self.next_execution()
        self._cached_next_exec = next_occurence(self._timedict, ignore_now=True)
        asyncio.run_coroutine_threadsafe(self._coro(self), self._mothership.bot.loop)

        if not self._repeat:
            self.cancel(lockless=True)

    def next_execution(self):
        return self._cached_next_exec

    def __str__(self):
        return "<timers.Job; coro: {}; td: {}>".format(self._coro, self._timedict)


def timedict(year=None, month=None, monthday=None, weekday=None, hour=None, minute=None):
    return {
        "year": year,
        "month": month,
        "monthday": monthday,
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
    }


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


def next_occurence(ntd, now=None, ignore_now=False):
    """
    Takes a normalized timedict and returns a datetime object that represents the next occurence of said timedict,
    taking now as starting point.
    :param ntd: normalized timedict
    :param now: datetime.datetime object from which to calculate; omit for current time
    :param ignore_now: If True: If the next occurence would be right now, returns the next occurence instead.
    :return datetime.datetime object that marks the next occurence; None if there is none
    """
    if now is None:
        now = datetime.datetime.now()

    weekdays = ntd["weekday"]
    if not weekdays:
        weekdays = [i for i in range(1, 8)]

    # Find date
    date = None
    startday = now.day
    for month, year in ring_iterator(ntd["month"], now.month, 12, now.year):

        # Check if this year is in the years list and if there even is a year in the future to be had
        if ntd["year"] is not None and year not in ntd["year"]:
            found = False
            for el in ntd["year"]:
                if el > year:
                    found = True
                    break
            if found:
                continue  # Wait for better years
            else:
                return None  # No future occurence found

        # Find day in month
        found = False
        for day in range(startday, monthrange(year, month)[1] + 1):
            if not datetime.date(year, month, day).weekday() + 1 in weekdays:
                continue

            if not ntd["monthday"] or day in ntd["monthday"]:

                # Find hour and minute
                starthour = 1
                startminute = 1
                onthisday = True

                # Today
                if year == now.year and month == now.month and day == now.day:
                    starthour = now.hour
                    startminute = now.minute

                    # Handle ignore_now flag
                    if ignore_now:
                        startminute += 1
                        if startminute >= 61:
                            startminute = 1
                            if starthour == 24:
                                continue  # nothing to do for this day
                            starthour += 1

                # find hour
                hour = None
                minute = None
                for hour, day_d in ring_iterator(ntd["hour"], starthour, 24, 0):
                    # wraparound
                    if day_d > 0:
                        onthisday = False
                        break

                    minute = nearest_element(startminute, ntd["minute"], 60)
                    if minute < startminute:
                        startminute = 1
                        continue
                    break

                if onthisday:
                    return datetime.datetime(year, month, day, hour, minute)

                # Continue loop
                found = True
                break
        if found:
            break
        startday = 1
