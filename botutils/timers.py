import asyncio
import logging
import datetime
import struct
from copy import deepcopy
from calendar import monthrange

from botutils.utils import execute_anything, execute_anything_sync, write_debug_channel


timedictformat = ["year", "month", "monthday", "weekday", "hour", "minute"]


class LastExecution(Exception):
    """
    Flow Control for non-repeating job execution
    """
    pass


class Job:
    """The scheduled Job representation"""
    def __init__(self, bot, td, f, data=None, repeat=True):
        """
        cron-like. Takes timedict elements as arguments.

        :param f: Function or coroutine with the signature f(Job). Gets called with this job instance as argument.
        :param td: Timedict that specifies the execution schedule
        :param data: Opaque object that is set as job.data
        :param repeat: If set to False, the job runs only once.
        :raises RuntimeError: raised if td is in the past
        """
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self._timedict = normalize_td(td)
        self._cancelled = False
        self._coro = f
        self._repeat = repeat

        self._timer = None
        self._lock = asyncio.Lock()

        self.data = data
        """
        Opaque value guaranteed to never be overwritten.
        It can be used to store arbitrary information to be used by the coroutine.
        """

        self._cached_next_exec = next_occurence(self._timedict, ignore_now=True)
        self._last_exec = None

        execute_anything_sync(self._loop)

    @property
    def timedict(self):
        """Copy of the timedict you passed to the registering function"""
        return deepcopy(self._timedict)

    @property
    def cancelled(self):
        """Gets if the job was cancelled"""
        return self._cancelled

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
        while self.next_execution() is not None:
            tts = (self.next_execution() - datetime.datetime.now()).seconds
            self.logger.debug("Scheduling job for {}".format(self.next_execution()))

            # check if tts is too big
            bitness = struct.calcsize("P") * 8
            if 2 ** (bitness - 3) < (365 * 24 * (60/2) * (60/2)):
                await write_debug_channel("Unable to sleep for {} years; job: {}"
                                          .format(self.next_execution().year, self))
                return

            # Schedule
            self._timer = Timer(self.bot, tts, self.loop_cb)
            self.logger.debug("Sleeping {} seconds".format(tts))
            await self._lock.acquire()
            if self._cancelled:
                self.logger.debug("Job was cancelled, cancelling loop")
                return
            self.logger.debug("Executing job {}".format(self))
            await execute_anything(self._coro, self)
            if not self._repeat:
                return

    def next_execution(self):
        """
        Returns a `datetime.datetime` object specifying the next execution of the job coroutine.
        Returns None if there is no future execution.

        :return: The datetime object of the next execution or None if no future execution.
        """
        now = datetime.datetime.now()
        delta = datetime.timedelta(seconds=10)
        if self._cached_next_exec is None or self._cached_next_exec - now < delta:
            self.logger.debug("Next occurence cache invalid")
            self._cached_next_exec = next_occurence(self._timedict, now=now + delta, ignore_now=True)
        self.logger.debug("Next execution: %s", self._cached_next_exec)
        return self._cached_next_exec

    def __str__(self):
        return "<timers.Job; coro: {}; td: {}>".format(self._coro, self._timedict)


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


def next_occurence_bottom_up(ntd, now=None, ignore_now=False):
    """
    Takes a normalized timedict and returns a datetime object that represents the next occurence of said timedict,
    taking now as starting point.

    :param ntd: normalized timedict
    :param now: datetime.datetime object from which to calculate; omit for current time
    :param ignore_now: If `True`: If the next occurence would be right now, returns the next occurence instead.
    :return: datetime.datetime object that marks the next occurence; `None` if there is none
    :raises NotImplementedError: Because this isn't done yet (supposed to replace top-down variant and introduce
        granularity down to seconds)
    """
    logger = logging.getLogger(__name__)
    logger.debug("Called next_occurence (bottom up) with ntd %s; now: %s; ignore_now: %s", ntd, now, ignore_now)
    if now is None:
        now = datetime.datetime.now()

    if ignore_now:
        now += datetime.timedelta(seconds=1)

    # find second
    second = now.second
    if "second" in ntd:
        second = nearest_element(now.second, ntd["second"], 0, 59)

    # find minute
    now_minute = now.minute if second >= now.second else now.minute + 1
    minute = now_minute
    if "minute" in ntd:
        minute = nearest_element(now_minute, ntd["minute"], 0, 59)

    # find hour
    now_hour = now.hour if minute >= now.minute else now.hour + 1
    hour = now_hour
    if "hour" in ntd:
        hour = nearest_element(now_hour, ntd["hour"], 0, 23)

    # find day
    now_day = now.day if hour >= now.hour else now.day + 1
    day = now_day
    if "day" in ntd:
        pass
    raise NotImplementedError("lint this lol {}".format(day))


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

        # Check if this year is in the years list and if there even is a year in the future to be had
        if ntd["year"] is not None and year not in ntd["year"]:
            logger.debug("year: %d; ntd[year]: %s", year, ntd["year"])
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
        self.has_run = False

        self.task = asyncio.create_task(self._task())
        self.logger.debug("Scheduled timer; t: %d, cb: %s", self.t, str(self.callback))

    async def _task(self):
        await asyncio.sleep(self.t)
        self.has_run = True
        execute_anything_sync(self.callback, *self.args, **self.kwargs)

    def skip(self):
        """
        Stops the timer and executes coro anyway.

        :raises HasAlreadyRun: Raised if `callback` was already scheduled (so nothing to skip).
        """
        if self.has_run:
            raise HasAlreadyRun(self.callback)
        self.task.cancel()
        self.has_run = True
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
