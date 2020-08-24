import datetime


def parse_time_input(*args):
    """
    Analyzes the given command args for following syntax and returns a datetime object after duration or on given
    date and/or time. If no duration unit (trailing m, h, d in arg[0]), minutes will be used.
    If no date and time can be determined, datetime.max will be returned.
    If for given date/time input some is missing, the current time, date or year will be used.

    [#|#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM]

    :param args: The command args for duration/date/time
    :returns: The datetime object with the given date and time or datetime.max
    """
    now = datetime.datetime.now()
    arg = " ".join(args)

    try:  # duration: #|#m|#h|#d
        if arg.endswith("m"):
            return now + datetime.timedelta(minutes=int(arg[:-1]))
        elif arg.endswith("h"):
            return now + datetime.timedelta(hours=int(arg[:-1]))
        elif arg.endswith("d"):
            return now + datetime.timedelta(days=int(arg[:-1]))
        else:
            return now + datetime.timedelta(minutes=int(arg))
    except ValueError:
        try:  # date: DD.MM.YYYY
            parsed = datetime.datetime.strptime(arg, "%d.%m.%Y")
            return datetime.datetime.combine(parsed.date(), now.time())
        except ValueError:
            try:  # time: HH:MM
                parsed = datetime.datetime.strptime(arg, "%H:%M")
                return datetime.datetime.combine(now.date(), parsed.time())
            except ValueError:
                try:  # full datetime: DD.MM.YYYY HH:MM
                    return datetime.datetime.strptime(arg, "%d.%m.%Y %H:%M")
                except ValueError:
                    try:  # datetime w/o year: DD.MM. HH:MM
                        parsed = datetime.datetime.strptime(arg, "%d.%m. %H:%M")
                        return datetime.datetime(now.year, parsed.month, parsed.day, parsed.hour, parsed.minute)
                    except ValueError:
                        pass

    # No valid time input
    return datetime.datetime.max
