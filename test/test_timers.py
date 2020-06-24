from datetime import date

from subsystems import timers


def test_cron_alg():
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
    for month, year in timers.ring_iterator(None, startmonth, 12, startyear):
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
