from datetime import timezone, date, datetime, time, timedelta


def to_local_time(timestamp):
    """
    Converts the given timestamp from UTC to local time
    :param timestamp: The datetime instance of the timestamp
    """
    return timestamp.replace(tzinfo=timezone.utc).astimezone(tz=None)


def from_epoch_ms(timestamp):
    """
    Converts the given timestamp from linux epoch in milliseconds to datetime object

    :param timestamp: linux epoch in ms
    :return: datetime object
    """
    return datetime.fromtimestamp(timestamp / 1000)


def parse_time_input(*args, end_of_day=False):
    """
    Analyzes the given command args for following syntax and returns a datetime object after duration or on given
    date and/or time. If no duration unit (trailing m, h, d), minutes will be used.
    If no date and time can be determined, datetime.max will be returned.
    If for given date/time input some is missing, the current time, date or year will be used, except if
    end_of_day is True, which indicates that 23:59 will be used as time.

    [#|#m|#h|#d|DD.MM.YYYY|DD.MM.|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]

    [#|#m|#h|#d|[DD.MM.[YYYY]] [HH:MM]]

    :param args: The command args for duration/date/time
    :param end_of_day: Use the end of the day (time 23:59) instead of current time if time is missing
    :returns: The datetime object with the given date and time or datetime.max
    """

    def unpack_tuple(t):
        arg_list = ""
        if isinstance(t, (tuple, list)):
            for el in t:
                arg_list += unpack_tuple(el)
        else:
            return "".join(t)
        return arg_list

    today = date.today()
    fill_time = time.max if end_of_day else datetime.now().time()
    arg = unpack_tuple(args).replace(" ", "")

    try:  # duration: #|#m|#h|#d
        if arg.endswith("m"):
            return datetime.now() + timedelta(minutes=int(arg[:-1]))
        elif arg.endswith("h"):
            return datetime.now() + timedelta(hours=int(arg[:-1]))
        elif arg.endswith("d"):
            return datetime.now() + timedelta(days=int(arg[:-1]))
        else:
            return datetime.now() + timedelta(minutes=int(arg))
    except ValueError:
        try:  # date: DD.MM.YYYY
            parsed = datetime.strptime(arg, "%d.%m.%Y")
            return datetime.combine(parsed.date(), fill_time)
        except ValueError:
            try:  # full datetime: DD.MM.YYYY HH:MM
                return datetime.strptime(arg, "%d.%m.%Y%H:%M")
            except ValueError:
                try:  # date: DD.MM
                    parsed = datetime.strptime(arg, "%d.%m.")
                    return datetime(today.year, parsed.month, parsed.day, fill_time.hour, fill_time.minute)
                except ValueError:
                    try:  # datetime w/o year: DD.MM. HH:MM
                        parsed = datetime.strptime(arg, "%d.%m.%H:%M")
                        return datetime(today.year, parsed.month, parsed.day, parsed.hour, parsed.minute)
                    except ValueError:
                        try:  # time: HH:MM
                            parsed = datetime.strptime(arg, "%H:%M")
                            return datetime.combine(today, parsed.time())
                        except ValueError:
                            pass

    # No valid time input
    return datetime.max


def hr_roughly(timestamp: datetime, now: datetime = None,
               fstring="{} {} ago", yesterday="yesterday", seconds="seconds", minutes="minutes",
               hours="hours", days="days", weeks="weeks", months="months", years="years"):
    """
    Builds a human-readable version of a rough approximation of a timedelta into the past, such as "2 minutes ago".
    :param timestamp: end timestamp of the measured distance
    :param now: start timestamp of the measured distance
    :param fstring: format string with two places for amount and time units
    :param yesterday: If the timedelta is roughly one day, this string is returned.
    :param seconds: Localized variant of "seconds"
    :param minutes: Localized variant of "minutes"
    :param hours: Localized variant of "hours"
    :param days: Localized variant of "days"
    :param weeks: Localized variant of "weeks"
    :param months: Localized variant of "months"
    :param years: Localized variant of "years"
    :return: human-readable approximation of the time distance between timestamp and now
    """
    if now is None:
        now = datetime.now()
    delta = now - timestamp
    if delta.seconds < 0:
        raise RuntimeError("Timestamp is not in the past")
    if delta.days >= 365 and years is not None:
        return fstring.format(delta.days // 365, years)
    if delta.days >= 31 and months is not None:
        return fstring.format(delta.days // 31, months)  # todo better month calc
    if delta.days >= 7 and weeks is not None:
        return fstring.format(delta.days // 7, weeks)
    if delta.days == 1 and yesterday is not None:
        return yesterday
    if delta.days >= 1 and days is not None:
        return fstring.format(delta.days, days)
    if delta.seconds >= 60*60 and hours is not None:
        return fstring.format(delta.seconds // (60*60), hours)
    if delta.seconds >= 60 and minutes is not None:
        return fstring.format(delta.seconds // 60, minutes)
    return fstring.format(delta.seconds, seconds)
