import logging

from datetime import date, datetime

from subsystems import timers

# pylint: disable=missing-function-docstring

DEBUG = False

if DEBUG:
    logging.basicConfig(level=logging.DEBUG)


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


def format_td(td):
    if td is None:
        return str(td)
    return "{}-{}-{}-{}-{}".format(td.year, td.month, td.day, td.hour, td.minute)


def tcase_cron_alg(now, td, expected, ignore_now=False):
    td = timers.next_occurence(timers.normalize_td(td), now=now, ignore_now=ignore_now)
    msg = "date is {}, should be {}".format(format_td(td), format_td(expected))
    assert (td is None and expected is None) or (td is not None and expected is not None), msg
    if td is None:
        return

    day = td.year == expected.year and td.month == expected.month and td.day == expected.day
    time = td.hour == expected.hour and td.minute == expected.minute
    assert day and time, msg


def test_cron_alg_past():
    now = datetime(year=2050, month=12, day=31, hour=23, minute=59)
    timedict = timers.timedict(year=1997, minute=3)
    expected = None
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_past_same_year():
    now = datetime(year=2021, month=7, day=31, hour=14, minute=11)
    timedict = timers.timedict(year=2021, month=5, monthday=3, hour=23, minute=0)
    expected = None
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_past_same_hour():
    now = datetime(year=2021, month=7, day=31, hour=14, minute=11)
    timedict = timers.timedict(year=2021, month=7, monthday=31, hour=14, minute=0)
    expected = None
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_past_same_day():
    now = datetime(year=2021, month=7, day=31, hour=14, minute=11)
    timedict = timers.timedict(year=2021, month=7, monthday=31, hour=13, minute=14)
    expected = None
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_past_same_month():
    now = datetime(year=2021, month=7, day=31, hour=14, minute=11)
    timedict = timers.timedict(year=2021, month=7, monthday=30, hour=13, minute=14)
    expected = None
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_hour0():
    now = datetime(year=2050, month=12, day=31, hour=23, minute=59)
    timedict = timers.timedict(minute=3)
    expected = datetime(year=2051, month=1, day=1, hour=0, minute=3)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute59_yearwrap():
    now = datetime(year=2050, month=12, day=31, hour=23, minute=59)
    timedict = timers.timedict(minute=0)
    expected = datetime(year=2051, month=1, day=1, hour=0, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute59_monthwrap():
    now = datetime(year=2050, month=11, day=30, hour=23, minute=59)
    timedict = timers.timedict(minute=0)
    expected = datetime(year=2050, month=12, day=1, hour=0, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute59_daywrap():
    now = datetime(year=2050, month=12, day=4, hour=23, minute=59)
    timedict = timers.timedict(minute=0)
    expected = datetime(year=2050, month=12, day=5, hour=0, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute59_hourwrap():
    now = datetime(year=2050, month=12, day=4, hour=14, minute=59)
    timedict = timers.timedict(minute=0)
    expected = datetime(year=2050, month=12, day=4, hour=15, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute0():
    now = datetime(year=2050, month=12, day=4, hour=14, minute=0)
    timedict = timers.timedict()
    expected = datetime(year=2050, month=12, day=4, hour=14, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_minute59_ignorenow():
    now = datetime(year=2050, month=12, day=4, hour=14, minute=59)
    timedict = timers.timedict()
    expected = datetime(year=2050, month=12, day=4, hour=15, minute=0)
    tcase_cron_alg(now, timedict, expected, ignore_now=True)


def test_cron_alg_minute0_ignorenow():
    now = datetime(year=2050, month=12, day=4, hour=14, minute=0)
    timedict = timers.timedict()
    expected = datetime(year=2050, month=12, day=4, hour=14, minute=1)
    tcase_cron_alg(now, timedict, expected, ignore_now=True)


def test_cron_alg_next_hour():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=31)
    timedict = timers.timedict(hour=13, minute=31)
    expected = datetime(year=2060, month=4, day=22, hour=13, minute=31)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_next_minute():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=31)
    timedict = timers.timedict(hour=12, minute=32)
    expected = datetime(year=2060, month=4, day=22, hour=12, minute=32)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_ignore_now():
    now = datetime(year=2060, month=4, day=22, hour=12, minute=32)
    timedict = timers.timedict(hour=12, minute=32)
    expected = datetime(year=2060, month=4, day=23, hour=12, minute=32)
    tcase_cron_alg(now, timedict, expected, ignore_now=True)


def test_cron_alg_nextmonth():
    now = datetime(year=2020, month=6, day=28, hour=18, minute=14)
    timedict = timers.timedict(year=2020, month=7, monthday=13, hour=20, minute=00)
    expected = datetime(year=2020, month=7, day=13, hour=20, minute=00)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_nextmonthnextyear():
    now = datetime(year=2021, month=6, day=28, hour=18, minute=14)
    timedict = timers.timedict(year=2021, month=7, monthday=13, hour=20, minute=00)
    expected = datetime(year=2021, month=7, day=13, hour=20, minute=00)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_sameday():
    now = datetime(year=2051, month=7, day=12, hour=14, minute=54)
    timedict = timers.timedict(year=2051, month=7, monthday=12, hour=18, minute=36)
    expected = datetime(year=2051, month=7, day=12, hour=18, minute=36)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_pasthournextday():
    now = datetime(year=2051, month=7, day=12, hour=19, minute=54)
    timedict = timers.timedict(hour=14, minute=0)
    expected = datetime(year=2051, month=7, day=13, hour=14, minute=0)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_futureyearpastday():
    now = datetime(year=2021, month=7, day=25, hour=12, minute=11)
    timedict = timers.timedict(year=2031, month=7, monthday=23, hour=15, minute=12)
    expected = datetime(year=2031, month=7, day=23, hour=15, minute=12)
    tcase_cron_alg(now, timedict, expected)


def test_cron_alg_futureyearpastmonth():
    now = datetime(year=2021, month=7, day=25, hour=12, minute=11)
    timedict = timers.timedict(year=2031, month=6, monthday=23, hour=15, minute=12)
    expected = datetime(year=2031, month=6, day=23, hour=15, minute=12)
    tcase_cron_alg(now, timedict, expected)


def test_fuzzer_01():
    now = datetime(year=2021, month=8, day=1, hour=15, minute=36)
    timedict = timers.timedict(year=2036, month=3, monthday=25, hour=6, minute=44)
    expected = datetime(year=2036, month=3, day=25, hour=6, minute=44)
    tcase_cron_alg(now, timedict, expected)


def test_fuzzer_02():
    now = datetime(year=2021, month=8, day=1, hour=15, minute=38)
    timedict = timers.timedict(year=2024, month=6, monthday=28, hour=7, minute=19)
    expected = datetime(year=2024, month=6, day=28, hour=7, minute=19)
    tcase_cron_alg(now, timedict, expected)
