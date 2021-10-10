from datetime import timezone, date, datetime, time, timedelta
from enum import Enum

from botutils.stringutils import sg_pl


def to_local_time(timestamp: datetime) -> datetime:
    """
    Converts the given timestamp from UTC to local time

    :param timestamp: The datetime instance of the timestamp
    :return: The timestamp w/o timezone information for local time
    """
    return timestamp.replace(tzinfo=timezone.utc).astimezone(tz=None)


class TimestampStyle(Enum):
    """Enum for the different possible style formats for a unix timestamp"""
    DATE_SHORT     = "d"  # 20/04/2021
    DATE_LONG      = "D"  # 20 April 2021
    DATETIME_SHORT = "f"  # 20 April 2021 16:20
    DATETIME_LONG  = "F"  # Tuesday, 20 April 2021 16:20
    RELATIVE       = "R"  # 2 months ago
    TIME_SHORT     = "t"  # 16:20
    TIME_LONG      = "T"  # 16:20:30


def to_unix_str(timestamp: datetime, style: TimestampStyle = TimestampStyle.DATETIME_SHORT) -> str:
    """
    Converts the given timestamp to a discord unix str

    :param timestamp: The datetime instance of the timestamp
    :param style: style of the outputted str
    :return: The string for this datetime
    """
    seconds = int((timestamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())
    return f"<t:{seconds}:{style.value}>"


def from_epoch_ms(timestamp: int) -> datetime:
    """
    Converts the given timestamp from linux epoch in milliseconds to datetime object

    :param timestamp: linux epoch in ms
    :return: datetime object from linux epoch time
    """
    return datetime.fromtimestamp(timestamp / 1000)


def parse_time_input(*args, end_of_day: bool = False) -> datetime:
    """
    Analyzes the given command args for following syntax and returns a datetime object after duration or on given
    date and/or time. If no duration unit (trailing m, h, d), minutes will be used.
    If no date and time can be determined, datetime.max will be returned.
    If for given date/time input some is missing, the current time, date or year will be used, except if
    end_of_day is True, which indicates that 23:59 will be used as time.

    [#|#m|#h|#d|DD.MM.YYYY|DD.MM.YY|DD.MM.|HH:MM|DD.MM.YYYY HH:MM|DD.MM.YY HH:MM|DD.MM. HH:MM]

    [#|#m|#h|#d|[DD.MM.[YY[YY]]] [HH:MM]]

    :param args: The command args for duration/date/time. Can also contain other leading or trailing
        args than time args, e.g. "be 14:00", which will be parsed to 2pm or today.
    :param end_of_day: Use the end of the day (time 23:59) instead of current time if time is missing
    :returns: The datetime object with the given date and time, or datetime.max if no datetime can be parsed.
    """

    def unpack_tuple(t):
        arg_list = []
        if isinstance(t, (tuple, list)):
            for el in t:
                arg_list += unpack_tuple(el)
        else:
            if t is not None:
                return t.split(" ")
            else:
                return ""
        return arg_list

    def parse_time(t):
        try:
            parsed = datetime.strptime(t, dt_format)
            r = datetime(parsed.year if '%Y' in dt_format else parsed.year if '%y' in dt_format else today.year,
                         parsed.month if '%m' in dt_format else today.month,
                         parsed.day if '%d' in dt_format else today.day,
                         parsed.hour if '%H' in dt_format else fill_time.hour,
                         parsed.minute if '%M' in dt_format else fill_time.minute)
            # use next year instead if the year was not specified and the date would be in the past
            if '%Y' not in dt_format and '%y' not in dt_format and r < datetime.now():
                r = datetime(r.year + 1, r.month, r.day, r.hour, r.minute)
            return r
        except ValueError:
            return None

    today = date.today()
    fill_time = time.max if end_of_day else datetime.now().time()
    unpacked = unpack_tuple(args)

    for i in range(len(unpacked)):
        arg = unpacked[i]
        try:
            # duration: #|#m|#h|#d (possible with . and , as comma separator)
            darg = arg.replace(",", ".") if "," in arg else arg

            if darg.endswith("m"):
                return datetime.now() + timedelta(minutes=float(darg[:-1]))
            if darg.endswith("h"):
                return datetime.now() + timedelta(hours=float(darg[:-1]))
            if darg.endswith("d"):
                return datetime.now() + timedelta(days=float(darg[:-1]))
            return datetime.now() + timedelta(minutes=float(darg))
        except ValueError:
            # the other possible formats
            darg = unpacked[i]
            if i < (len(unpacked) - 1):
                darg = " ".join(unpacked[i:i + 2])
            for dt_format in ["%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m. %H:%M"]:
                pvalue = parse_time(darg)
                if pvalue is not None:
                    return pvalue

            for dt_format in ["%d.%m.%Y", "%d.%m.%y", "%d.%m.", "%H:%M"]:
                pvalue = parse_time(arg)
                if pvalue is not None:
                    return pvalue

    # No valid time input
    return datetime.max


def hr_roughly(timestamp: datetime, now: datetime = None,
               fstring: str = "{} {} ago", yesterday: str = "yesterday", seconds: str = "seconds",
               seconds_sg: str = "second", minutes: str = "minutes", minutes_sg: str = "minute", hours: str = "hours",
               hours_sg: str = "hour", days: str = "days", days_sg: str = "day", weeks: str = "weeks",
               weeks_sg: str = "week", months: str = "months", months_sg: str = "month", years: str = "years",
               years_sg: str = "year") -> str:
    """
    Builds a human-readable version of a rough approximation of a timedelta into the past, such as "2 minutes ago".

    :param timestamp: end timestamp of the measured distance
    :param now: start timestamp of the measured distance
    :param fstring: format string with two places for amount and time units
    :param yesterday: If the timedelta is roughly one day, this string is returned.
    :param seconds: Localized variant of "seconds"
    :param seconds_sg: Localized variant of "second"
    :param minutes: Localized variant of "minutes"
    :param minutes_sg: Localized variant of "minute"
    :param hours: Localized variant of "hours"
    :param hours_sg: Localized variant of "hour"
    :param days: Localized variant of "days"
    :param days_sg: Localized variant of "day"
    :param weeks: Localized variant of "weeks"
    :param weeks_sg: Localized variant of "week"
    :param months: Localized variant of "months"
    :param months_sg: Localized variant of "month"
    :param years: Localized variant of "years"
    :param years_sg: Localized variant of "year"
    :return: human-readable approximation of the time distance between timestamp and now
    :raises RuntimeError: If timestamp is not in past
    """
    if now is None:
        now = datetime.now()
    delta = now - timestamp
    if delta.seconds < 0:
        raise RuntimeError("Timestamp is not in the past")

    amount = delta.days // 365
    if amount > 0 and years is not None:
        return fstring.format(amount, sg_pl(amount, years_sg, years))

    amount = delta.days // 31  # todo better month calc
    if amount > 0 and months is not None:
        return fstring.format(amount, sg_pl(amount, months_sg, months))

    amount = delta.days // 7
    if amount > 0 and weeks is not None:
        return fstring.format(amount, sg_pl(amount, weeks_sg, weeks))

    if delta.days == 1 and yesterday is not None:
        return yesterday

    if delta.days >= 1 and days is not None:
        return fstring.format(delta.days, sg_pl(delta.days, days_sg, days))

    amount = delta.seconds // (60 * 60)
    if amount > 0 and hours is not None:
        return fstring.format(amount, sg_pl(amount, hours_sg, hours))

    amount = delta.seconds // 60
    if amount > 0 and minutes is not None:
        return fstring.format(amount, sg_pl(amount, minutes_sg, minutes))
    return fstring.format(delta.seconds, sg_pl(delta.seconds, seconds_sg, seconds))
