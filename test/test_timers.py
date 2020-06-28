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


def test_cron_alg_next_hour():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=31)
    timedict = timers.timedict(hour=13, minute=31)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2060, 4, 22, 13, 31)
    assert td.year == 2060 and td.month == 4 and td.day == 22 and td.hour == 13 and td.minute == 31, msg


def test_cron_alg_next_minute():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=31)
    timedict = timers.timedict(hour=12, minute=32)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2060, 4, 22, 12, 32)
    assert td.year == 2060 and td.month == 4 and td.day == 22 and td.hour == 12 and td.minute == 32, msg


def test_cron_alg_ignore_now():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=32)
    timedict = timers.timedict(hour=12, minute=32)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now, ignore_now=True)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2060, 4, 23, 12, 32)
    assert td.year == 2060 and td.month == 4 and td.day == 23 and td.hour == 12 and td.minute == 32, msg


def test_cron_alg_nextmonth():
    now = datetime(year=2020, month=6, day=28, hour=18, minute=14)
    timedict = timers.timedict(year=2020, month=7, monthday=13, hour=20, minute=00)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now, ignore_now=True)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2020, 7, 13, 20, 00)
    assert td.year == 2020 and td.month == 7 and td.day == 13 and td.hour == 20 and td.minute == 00, msg


def test_cron_alg_nextmonthnextyear():
    now = datetime(year=2021, month=6, day=28, hour=18, minute=14)
    timedict = timers.timedict(year=2021, month=7, monthday=13, hour=20, minute=00)
    td = timers.next_occurence(timers.normalize_td(timedict), now=now, ignore_now=True)
    assert td is not None, "timers.next_occurence didn't return anything"
    msg = "date is {}-{}-{}-{}-{}, should be {}-{}-{}-{}-{}".format(
        td.year, td.month, td.day, td.hour, td.minute, 2021, 7, 13, 20, 00)
    assert td.year == 2021 and td.month == 7 and td.day == 13 and td.hour == 20 and td.minute == 00, msg
