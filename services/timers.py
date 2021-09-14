"""
This subsystem provides cron-like timers whose execution are scheduled to run at a specific time in the future,
periodically or only once.
"""

from copy import deepcopy
from calendar import monthrange
import asyncio
import logging
import struct
import datetime

from base.configurable import BaseSubsystem
from botutils.utils import write_debug_channel, execute_anything_sync, execute_anything, log_exception

timedictformat = ["year", "month", "monthday", "weekday", "hour", "minute"]


class NoFutureExec(Exception):
    """
    Raised by Mothership.schedule() when there is no execution in the future (i.e. all execs are in the past).
    """
    pass


class LastExecution(Exception):
    """
    Flow Control for non-repeating job execution
    """
    pass


class Mothership(BaseSubsystem):
    """
    The timer subsystem allows for a periodic or singular coroutine to be scheduled based
     on a time distance or a calendar-oriented schedule.

    Timers do not survive bot restarts.
    """

    def __init__(self, bot):
        BaseSubsystem.__init__(self, bot)
        self.bot = bot
        self.jobs = []
        self.logger = logging.getLogger(__name__)

    def schedule(self, coro, td, data=None, repeat=True, ignore_now=False):
        """
        cron-like. Takes timedict elements as arguments.

        :param coro: Coroutine with the signature f(Cancellable).
        :param td: Timedict that specifies the execution schedule
        :param data: Opaque object that is set as job.data
        :param repeat: If set to False, the job runs only once.
        :param ignore_now: If set to True, skips the current minute for timer execution
        :raises NoFutureExec: raised if td is in the past
        """
        td = normalize_td(td)
        if next_occurence(td) is None:
            raise NoFutureExec("td {} is in the past".format(td))
        job = Job(self.bot, td, coro, data=data, repeat=repeat, ignore_now=ignore_now)
        self.logger.info("Scheduling %s", job)
        self.jobs.append(job)
        return job

    def remove(self, job):
        self.logger.debug("Removing job %s", job)
        self.jobs.remove(job)


class Job:
    """The scheduled Job representation"""
    def __init__(self, bot, td, f, data=None, repeat=True, run=True, ignore_now=False):
        """
        cron-like. Takes timedict elements as arguments.

        :param f: Function or coroutine with the signature f(Job). Gets called with this job instance as argument.
        :param td: Timedict that specifies the execution schedule
        :param data: Opaque object that is set as job.data
        :param repeat: If set to False, the job runs only once.
        :param run: Set to False to not automatically start this job
        :param ignore_now: If set to True, the timer is not executed in the current minute.
        :raises RuntimeError: raised if td is in the past
        """
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self._timedict = normalize_td(td)
        self._cancelled = False
        self._coro = f
        self._repeat = repeat
        self._passthrough = False
        self._ignore_now = ignore_now

        self._timer = None
        self._lock = asyncio.Lock()
        self._task = None

        """
        Opaque value guaranteed to never be overwritten.
        It can be used to store arbitrary information to be used by the coroutine.
        """
        self.data = data

        self._is_scheduled = False
        self._last_tts = 0

        self._cached_next_exec = next_occurence(self._timedict, ignore_now=ignore_now)
        self._last_exec = None

        if run:
            self._task = execute_anything_sync(self._loop())

    @property
    def timedict(self):
        """Copy of the timedict you passed to the registering function"""
        return deepcopy(self._timedict)

    @property
    def cancelled(self):
        """Gets if the job was cancelled"""
        return self._cancelled

    @property
    def is_scheduled(self):
        return self._is_scheduled

    def cancel(self):
        """
        Cancels the job

        :raises RuntimeError: If the job was already cancelled"""
        if self._cancelled:
            raise RuntimeError("Already cancelled")
        self.logger.info("Cancelling %s", self)
        self._cancelled = True
        self._timer.cancel()
        self._lock.release()

    def loop_cb(self):
        self._lock.release()

    async def _loop(self):
        await self._lock.acquire()
        first = True
        while True:
            ignore_now = True
            if first:
                ignore_now = self._ignore_now
                first = False
            next_exec = self.next_execution(ignore_now=ignore_now)
            if next_exec is None:
                break

            tts = (next_exec - datetime.datetime.now()).total_seconds()
            self._last_tts = int(tts)
            self.logger.debug("Scheduling job for %s", next_exec)

            # check if tts is too big
            bitness = struct.calcsize("P") * 8
            if 2 ** (bitness - 3) < (365 * 24 * (60/2) * (60/2)):
                await write_debug_channel("Unable to sleep for {} years; job: {}"
                                          .format(next_exec.year, self))
                break

            # Schedule
            self._is_scheduled = True
            self._timer = Timer(self.bot, tts, self.loop_cb)
            self.logger.debug("Sleeping %d seconds, that's roughly %d days", tts, self._last_tts // (60*60*24))
            if not self._passthrough:
                await self._lock.acquire()
            self._passthrough = False
            if self._cancelled:
                self.logger.debug("Job was cancelled, cancelling loop")
                break
            self.logger.debug("Executing job %s", self)
            try:
                await execute_anything(self._coro, self)
            except Exception as e:
                fields = {
                    "timedict": self._timedict
                }
                await log_exception(e, title=":x: Timer error (scheduled)", fields=fields)
            if not self._repeat:
                break

        self._is_scheduled = False
        self.bot.timers.remove(self)

    def execute(self):
        """
        Executes this job. Does not check if it is actually scheduled to be executed.
        """
        self.logger.debug("Executing job %s ahead of schedule", self)
        execute_anything_sync(self._coro, self)
        if not self._repeat and self._timer:
            self._timer.cancel()

    def next_execution(self, ignore_now=True):
        """
        Returns a `datetime.datetime` object specifying the next execution of the job coroutine.
        Returns None if there is no future execution.

        :param ignore_now: Ignores the current minute
        :return: The datetime object of the next execution or None if no future execution.
        """
        now = datetime.datetime.now()
        delta = datetime.timedelta(seconds=10)
        if self._cached_next_exec is None or self._cached_next_exec - now < delta:
            self.logger.debug("Next occurence cache invalid")
            self._cached_next_exec = next_occurence(self._timedict, now=now + delta, ignore_now=ignore_now)
        self.logger.debug("Next execution: %s", self._cached_next_exec)
        return self._cached_next_exec

    def __str__(self):
        return "<timers.Job; coro: {}; td: {}; is scheduled: {}; last tts: {} ({} days)>".format(
            self._coro, self._timedict, self._is_scheduled, self._last_tts, self._last_tts // (60*60*24))


def timedict(year=None, month=None, monthday=None, weekday=None, hour=None, minute=None):
    """Creates a timedict object for scheduling a job"""
    return {
        "year": year,
        "month": month,
        "monthday": monthday,
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
    }


def timedict_by_datetime(dt):
    """
    Creates a timedict that corresponds to a datetime object and can be used by schedule().

    :param dt: datetime.datetime or datetime.date object
    :return: corresponding timedict to be used by schedule()
    :raises TypeError: If dt is not a datetime or date object
    """
    if isinstance(dt, datetime.datetime):
        return timedict(year=dt.year, month=dt.month, monthday=dt.day, hour=dt.hour, minute=dt.minute)
    if isinstance(dt, datetime.date):
        return timedict(year=dt.year, month=dt.month, monthday=dt.day)
    else:
        raise TypeError


def normalize_td(td):
    """
    Normalizes a timedict to consist of only lists. Also validates formats.

    :return: Normalized timedict;
    :raises TypeError: If td is not a valid timedict
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
            except TypeError as e:
                if not isinstance(td[el], int):
                    raise TypeError("Expecting an int or a list of ints as {}".format(el)) from e
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
    :raises RuntimeError: If startel is not in haystack
    """
    logging.getLogger(__name__).debug("Called ringiterator(%s, %s, %s, %s, %s)",
                                      haystack, startel, ringstart, ringend, startperiod)
    if haystack is None:
        haystack = range(ringstart, ringend + 1)

    # Check if startel is actually in haystack
    try:
        i = haystack.index(startel)
    except ValueError as e:
        raise RuntimeError("{} is not in haystack".format(startel)) from e

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
    :param ignore_now: If `True`: If the next occurence would be right now, returns the next occurence instead.
    :return: datetime.datetime object that marks the next occurence; `None` if there is none
    """
    logger = logging.getLogger(__name__)
    logger.debug("Called next_occurence with ntd %s; now: %s; ignore_now: %s", ntd, now, ignore_now)
    if now is None:
        now = datetime.datetime.now()

    if ignore_now:
        now += datetime.timedelta(minutes=1)

    weekdays = ntd["weekday"]
    if not weekdays:
        weekdays = list(range(1, 8))

    # Find date
    startmonth = nearest_element(now.month, ntd["month"], 1, 12)
    startday = 1
    if startmonth == now.month:
        startday = now.day
    for month, year in ring_iterator(ntd["month"], startmonth, 1, 12, now.year):
        logger.debug("Checking %d-%d", year, month)

        # Check if we're in the past
        if year < now.year or (year == now.year and month < now.month):
            logger.debug("We're in the past")
            continue

        # Check if this year is in the years list and if there even is a year in the future to be had
        if ntd["year"] is not None and year not in ntd["year"]:
            logger.debug("year: %d; ntd[year]: %s", year, ntd["year"])
            startmonth = 1
            startday = 1
            for el in ntd["year"]:
                if el > year:
                    break  # Wait for better years
            else:
                logger.debug("No future occurence found")
                return None  # No future occurence found
            continue

        # Find day in month
        for day in range(startday, monthrange(year, month)[1] + 1):
            logger.debug("Checking day %d", day)
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
            if next_hour < starthour:
                logger.debug("next_hour %d < starthour %d", next_hour, starthour)
                continue
            for hour, day_d in ring_iterator(ntd["hour"], next_hour, 0, 23, 0):
                logger.debug("Checking hour %d", hour)
                # day wraparound
                if day_d > 0:
                    logger.debug("Next day (wraparound)")
                    onthisday = False
                    break

                # find minute
                if year == now.year and month == now.month and day == now.day and hour == now.hour:
                    startminute = now.minute

                minute = nearest_element(startminute, ntd["minute"], 0, 59)
                logger.debug("Checking minute %d", minute)
                if minute < startminute:
                    logger.debug("minute %d < startminute %d", minute, startminute)
                    startminute = 0
                    continue
                logger.debug("Correct minute found: %d", minute)
                break  # correct minute found

            if onthisday:
                return datetime.datetime(year, month, day, hour, minute)
            # Nothing found on this day of the month
            continue

        # Month is over
        startday = 1

    logger.warning("Yes, this line happens and can be removed. If it doesn't, we should raise a RuntimeError here.")
    return None


class HasAlreadyRun(Exception):
    """
    Is raised by AsyncTimer if cancel() comes too late
    """

    def __init__(self, callback):
        super().__init__("Timer callback has already run, callback was {}".format(callback))


class Timer:
    """
    Cancellable and skippable timer that executes a function or coroutine after a given amount of time has passed.
    """
    def __init__(self, bot, t, callback, *args, **kwargs):
        """

        :param bot: Geckarbot ref
        :param t: time in seconds
        :param callback: scheduled when t seconds have passed
        :param args: callback args
        :param kwargs: callback kwargs
        """
        self.logger = logging.getLogger()
        self.bot = bot
        self.t = t
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

        self.cancelled = False
        self._has_run = False

        self.task = execute_anything_sync(self._task())
        self.logger.debug("Scheduled timer; t: %d, cb: %s", self.t, str(self.callback))

    @property
    def has_run(self):
        return self._has_run

    async def _task(self):
        """
        Executes the timer's callback after waiting `t` seconds.
        """
        await asyncio.sleep(self.t)
        self._has_run = True
        try:
            await execute_anything(self.callback, *self.args, **self.kwargs)
        except Exception as e:
            fields = {"Callback": "`{}`".format(self.callback)}
            await log_exception(e, title=":x: Timer error", fields=fields)

    def skip(self):
        """
        Stops the timer and executes coro anyway.

        :raises HasAlreadyRun: Raised if `callback` was already scheduled (so nothing to skip).
        """
        if self.has_run:
            raise HasAlreadyRun(self.callback)
        self.task.cancel()
        self._has_run = True
        execute_anything_sync(self.callback, *self.args, **self.kwargs)

    def cancel(self):
        """
        Cancels the timer.

        :raises HasAlreadyRun: Raised if `callback` was already scheduled (so the cancellation comes too late).
        """
        if self.has_run:
            raise HasAlreadyRun(self.callback)
        self.task.cancel()
        self.cancelled = True
