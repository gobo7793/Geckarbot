from copy import deepcopy
from calendar import monthrange
from threading import Thread, Lock
from time import sleep
import sys
import asyncio
import logging
import warnings
import datetime

from base import BaseSubsystem


"""
This subsystem provides cron-like timers whose execution are scheduled to run at a specific time in the future,
periodically or only once.
"""


timedictformat = ["year", "month", "monthday", "weekday", "hour", "minute"]


class LastExecution(Exception):
    """
    Flow Control for non-repeating job execution
    """
    pass


class Mothership(BaseSubsystem, Thread):
    def __init__(self, bot, launch_immediately=True):
        BaseSubsystem.__init__(self, bot)
        Thread.__init__(self)
        self.bot = bot
        self.jobs = []
        self._to_register = []
        self._to_cancel = []
        self._lock = Lock()
        self._shutdown = None
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

                # Handle cancellations
                for el in self._to_cancel:
                    if el in self.jobs:
                        self.jobs.remove(el)
                self._to_cancel = []

                # Handle executions
                now = datetime.datetime.now()
                executed = []
                todel = []
                for el in self.jobs:
                    if (el.next_execution() - now).total_seconds() < 10:  # with this, it should always be < 0
                        try:
                            el.execute()
                            executed.append(el)
                        except LastExecution:
                            todel.append(el)
                    else:
                        break
                for el in executed:
                    self.logger.debug("Executed job {}; scheduling re-execution".format(el))
                    self.jobs.remove(el)
                    self._to_register.append(el)
                for el in todel:
                    self.logger.debug("Executed job {}; this was the last execution".format(el))
                    self.jobs.remove(el)

            tts = 60 - datetime.datetime.now().second + 1
            sleep(tts)

    def insert_job(self, job):
        """
        Inserts a job at the correct position in the job list.
        """
        nexto = job.next_execution()
        found = False
        for i in range(len(self.jobs)):
            next_execution = self.jobs[i].next_execution()
            if next_execution is not None and next_execution > nexto:
                found = True
                self.jobs.insert(i, job)
                break
        if not found:
            self.jobs.append(job)

    def cancel(self, job):
        self._to_cancel.append(job)

    def schedule(self, coro, td, repeat=True):
        """
        cron-like. Takes timedict elements as arguments.
        :param coro: Coroutine with the signature f(Cancellable).
        :param td: Timedict that specifies the execution schedule
        :param repeat: If set to False, the job runs only once.
        """
        job = Job(self, td, coro, repeat=repeat)
        self.logger.info("Scheduling {}".format(job))
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

    def cancel(self):
        self._mothership.logger.info("Cancelling {}".format(self))
        self._cancelled = True
        self._mothership.cancel(self)

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

        self._mothership.logger.info("Executing {} at {}".format(self, self.next_execution()))
        self._last_exec = self.next_execution()
        self._cached_next_exec = next_occurence(self._timedict, ignore_now=True)
        asyncio.run_coroutine_threadsafe(self._coro(self), self._mothership.bot.loop)

        if not self._repeat or self.next_execution() is None:
            self.cancel()
            # raise LastExecution  # alternatively

    def next_execution(self):
        if self._cached_next_exec is None:
            self._cached_next_exec = next_occurence(self._timedict)
        self._mothership.logger.info("Next execution: {}".format(self._cached_next_exec))
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
            if td[el] != 0 and not td[el]:
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


def ringdistance(a, b, ringstart, ringend):
    """
    Returns the smallest positive forward-distance between b and a in a ring of the form ringstart..ringend, e.g.:
    ringdistance(1, 3, 1, 12) == 2   # january, march
    ringdistance(3, 1, 1, 12) == 10  # march, january
    ringdistance(21, 1, 0, 23) == 4  # 9 pm, 1 am
    """
    if not ringstart <= b <= ringend or not ringstart <= a <= ringend:
        raise ValueError("Expecting {} and {} to be between {} and {}".format(b, a, ringstart, ringend))

    if a <= b:
        return b - a
    else:
        return ringend - a + b - (ringstart - 1)


def nearest_element(me, haystack, ringstart, ringend):
    """
    Finds the element in haystack that is the closest to me in a forward-distance. Assumes a ring of ringstart..ringend.
    If haystack is None, returns me. Distance of 0 counts.
    """
    if haystack is None:
        return me

    r = haystack[0]
    last_distance = ringdistance(me, haystack[0], ringstart, ringend)
    for i in range(1, len(haystack)):
        d = ringdistance(me, haystack[i], ringstart, ringend)
        if d < last_distance:
            last_distance = d
            r = haystack[i]
    return r


def ring_iterator(haystack, startel, ringstart, ringend, startperiod):
    """
    Iterates forever over all ring elements in haystack, beginning with startel. Assumes a ring of ringstart..ringend.
    :param haystack: The haystack with elements in the ring
    :param startel: haystack element to start the loop with; this is always the first element to be yielded
    :param ringstart: first element of the ring
    :param ringend: last element of the ring, so the ring is ringstart..ringend
    :param startperiod: This value is iterated every cycle and returned as endperiod.
    :return: haystackelement, endperiod
    """
    logging.getLogger(__name__).debug("Called ringiterator({}, {}, {}, {}, {})"
                                      .format(haystack, startel, ringstart, ringend, startperiod))
    if haystack is None:
        haystack = [i for i in range(ringstart, ringend + 1)]

    # Check if startel is actually in haystack
    i = None
    for k in range(len(haystack)):
        if haystack[k] == startel:
            i = k
    if i is None:
        raise RuntimeError("{} is not in haystack".format(startel))

    # Actual generator
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
    logger = logging.getLogger(__name__)
    if now is None:
        now = datetime.datetime.now()

    weekdays = ntd["weekday"]
    if not weekdays:
        weekdays = [i for i in range(1, 8)]

    # Find date
    startmonth = nearest_element(now.month, ntd["month"], 1, 12)
    startday = 1
    if startmonth == now.month:
        startday = now.day
    for month, year in ring_iterator(ntd["month"], startmonth, 1, 12, now.year):
        logger.debug("Checking {}-{}".format(year, month))

        # Check if this year is in the years list and if there even is a year in the future to be had
        if ntd["year"] is not None and year not in ntd["year"]:
            logger.debug("year: {}; ntd[year]: {}".format(year, ntd["year"]))
            found = False
            for el in ntd["year"]:
                if el > year:
                    found = True
                    break
            if found:
                continue  # Wait for better years
            else:
                logger.debug("No future occurence found")
                return None  # No future occurence found

        # Find day in month
        for day in range(startday, monthrange(year, month)[1] + 1):
            logger.debug("Checking day {}".format(day))
            # Not our day of week
            if not datetime.date(year, month, day).weekday() + 1 in weekdays:
                continue

            # Not our day of month
            if ntd["monthday"] is not None and day not in ntd["monthday"]:
                continue

            # Find hour and minute
            starthour = 0
            startminute = 0
            onthisday = True

            # Today
            if year == now.year and month == now.month and day == now.day:
                starthour = now.hour

            # find hour
            hour = None
            minute = None
            next_hour = nearest_element(starthour, ntd["hour"], 0, 23)
            for hour, day_d in ring_iterator(ntd["hour"], next_hour, 0, 23, 0):
                logger.debug("Checking hour {}".format(hour))
                # wraparound
                if day_d > 0:
                    logger.debug("Next day (wraparound)")
                    onthisday = False
                    break

                # find minute
                if year == now.year and month == now.month and day == now.day and hour == now.hour:
                    startminute = now.minute

                    # Handle ignore_now flag
                    if ignore_now:
                        startminute += 1
                        if startminute >= 60:
                            startminute = 0
                            starthour += 1
                            if starthour == 24:
                                continue  # nothing to do for this day

                minute = nearest_element(startminute, ntd["minute"], 0, 59)
                logger.debug("Checking minute {}".format(minute))
                if minute < startminute:
                    logger.debug("minute {} < startminute {}".format(minute, startminute))
                    startminute = 0
                    continue
                logger.debug("Correct minute found: {}".format(minute))
                break  # correct minute found

            if onthisday:
                return datetime.datetime(year, month, day, hour, minute)
            else:
                # Nothing found on this day of the month
                continue

        # Month is over
        startday = 1


"""
Old AsyncTimer; TODO slowly merge into Mothership
"""


class HasAlreadyRun(Exception):
    """
    Is raised by AsyncTimer if cancel() comes too late
    """

    def __init__(self, callback):
        super().__init__("Timer callback has already run, callback was {}".format(callback))


# todo move to subsystems.timers and slowly merge into it
class AsyncTimer(Thread):
    def __init__(self, bot, t, callback, *args, **kwargs):
        warnings.warn("utils.AsyncTimer is deprecated.")
        self.logger = logging.getLogger(__name__)
        self.loop = bot.loop

        self.t = t
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

        self.cancelled = False
        self.has_run = False
        self.cancel_lock = Lock()

        super().__init__()
        self.start()

    def run(self):
        self.logger.debug("Running timer, will be back in {} seconds (callback: {})".format(self.t, self.callback))
        sleep(self.t)

        with self.cancel_lock:
            if self.cancelled:
                self.logger.debug("Timer was cancelled (callback: {})".format(self.callback))
                return
            self.has_run = True
            self.logger.debug("Timer over, running callback {}".format(self.callback))

            try:
                asyncio.run_coroutine_threadsafe(self.callback(*self.args, **self.kwargs), self.loop)
            except Exception as e:
                self.logger.error(e)
                raise e

    def cancel(self):
        with self.cancel_lock:
            if self.has_run:
                raise HasAlreadyRun(self.callback)
            self.cancelled = True
