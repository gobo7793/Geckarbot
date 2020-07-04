import unittest
import datetime
from botutils import utils


class TestUtils(unittest.TestCase):
    def test_analyze_time_input(self):
        now = datetime.datetime.now()
        d = utils.analyze_time_input("4")
        self.assertEqual(now + datetime.timedelta(minutes=4), d)
        now = datetime.datetime.now()
        d = utils.analyze_time_input("4m")
        self.assertEqual(now + datetime.timedelta(minutes=4), d)
        now = datetime.datetime.now()
        d = utils.analyze_time_input("4h")
        self.assertEqual(now + datetime.timedelta(hours=4), d)
        now = datetime.datetime.now()
        d = utils.analyze_time_input("4d")
        self.assertEqual(now + datetime.timedelta(days=4), d)
        d = utils.analyze_time_input("07.12.2020")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15).date(), d.date())
        d = utils.analyze_time_input("14:15")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15).time(), d.time())
        d = utils.analyze_time_input("07.12.2020 14:15")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15), d)
        now = datetime.datetime.now()
        d = utils.analyze_time_input("07.12.", "14:15")
        self.assertEqual(datetime.datetime(now.year, 12, 7, 14, 15), d)
        d = utils.analyze_time_input("abcd")
        self.assertEqual(datetime.datetime.max, d)


if __name__ == '__main__':
    unittest.main()
