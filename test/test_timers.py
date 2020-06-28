from datetime import date, datetime

from subsystems import timers


def test_cron_alg_fr13():
    # find next friday 13th
    today = date.today()
    startmonth = today.month
    startyear = today.year
    if today.day > 13:
        startmonth += 1
    if startmonth > 12:
        startmonth = 1
        startyear += 1
    fr13year = None
    fr13month = None
    for month, year in timers.ring_iterator(None, startmonth, 1, 12, startyear):
        print("checking {}, {}".format(month, year))
        if date(year, month, 13).weekday() == 4:
            fr13year = year
            fr13month = month
            break

    # actual test
    timedict = {"monthday": 13, "weekday": 5}
    testdate = timers.next_occurence(timers.normalize_td(timedict))
    msg = "date is {}-{}-{}, should be {}-{}-{}".format(testdate.year, testdate.month, testdate.day,
                                                        fr13year, fr13month, 13)
    assert testdate.year == fr13year and testdate.month == fr13month and testdate.day == 13, msg

    # Check for a year in the future
    year = today.year + 2
    timedict = {"year": year, "monthday": 13, "weekday": 5}
    testdate = timers.next_occurence(timers.normalize_td(timedict))
    assert testdate.year == year


def test_cron_alg_hour0():
    now = datetime(year=2050, month=12, day=31, hour=23, minute=59)
    timedict = timers.timedict(minute=3)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2051, 1, 1, 0, 3)
    assert td.year == 2051 and td.month == 1 and td.day == 1 and td.hour == 0 and td.minute == 3, msg


def test_cron_alg_minute0():
    now = datetime(year=2050, month=12, day=31, hour=23, minute=59)
    timedict = timers.timedict(minute=0)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2051, 1, 1, 0, 0)
    assert td.year == 2051 and td.month == 1 and td.day == 1 and td.hour == 0 and td.minute == 0, msg
