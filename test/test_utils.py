import unittest
import datetime

from Geckarbot import Geckarbot
from botutils import permchecks, timeutils


class TestUtils(unittest.TestCase):
    """Test various bot utils"""

    def test_analyze_time_input(self):
        """Tests `botutils.timeutils.parse_time_input()`"""
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4")
        self.assertEqual(now + datetime.timedelta(minutes=4), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4m")
        self.assertEqual(now + datetime.timedelta(minutes=4), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4h")
        self.assertEqual(now + datetime.timedelta(hours=4), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4d")
        self.assertEqual(now + datetime.timedelta(days=4), d)
        d = timeutils.parse_time_input("4,5")
        self.assertEqual(now + datetime.timedelta(minutes=4, seconds=30), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4,5m")
        self.assertEqual(now + datetime.timedelta(minutes=4, seconds=30), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4,5h")
        self.assertEqual(now + datetime.timedelta(hours=4, minutes=30), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("4,5d")
        self.assertEqual(now + datetime.timedelta(days=4, hours=12), d)

        d = timeutils.parse_time_input("07.12.2020")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15).date(), d.date())
        d = timeutils.parse_time_input("14:15")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15).time(), d.time())
        d = timeutils.parse_time_input("07.12.2020 14:15")
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15), d)
        now = datetime.datetime.now()
        d = timeutils.parse_time_input("07.12.", "14:15")
        self.assertEqual(datetime.datetime(now.year, 12, 7, 14, 15), d)

        d = timeutils.parse_time_input("abcd")
        self.assertEqual(datetime.datetime.max, d)
        arg_list = ("07.12.2020", "14:15")
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(2020, 12, 7, 14, 15), d)
        arg_list = ("11.07.", "18:36")
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, 18, 36), d)
        arg_list = "11.07."
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, now.hour, now.minute), d)
        arg_list = "11.07."
        d = timeutils.parse_time_input(arg_list, end_of_day=True)
        self.assertEqual(datetime.datetime(now.year, 7, 11, now.time().max.hour, now.time().max.minute), d)

        arg_list = "am 11.07."
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, now.hour, now.minute), d)
        arg_list = "bis 11.07. done"
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, now.hour, now.minute), d)
        arg_list = "bis 11.07. 12:50 done"
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, 12, 50), d)
        arg_list = "bis 11.07. 12:50"
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, 12, 50), d)
        arg_list = ("11.07.", "done")
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, now.hour, now.minute), d)
        arg_list = "11.07. 12:50 done"
        d = timeutils.parse_time_input(arg_list)
        self.assertEqual(datetime.datetime(now.year, 7, 11, 12, 50), d)

    def test_debug_user_check(self):
        """Tests the debug user detection of the bot"""
        bot = Geckarbot
        bot.DEBUG_MODE = False
        bot.DEBUG_USERS = [1, 2, 3]

        self.assertEqual(permchecks.debug_user_check_id(1), True)
        self.assertEqual(permchecks.debug_user_check_id(4), True)

        bot.DEBUG_MODE = True

        self.assertEqual(permchecks.debug_user_check_id(1), True)
        self.assertEqual(permchecks.debug_user_check_id(4), False)

        bot.DEBUG_USERS = []

        self.assertEqual(permchecks.debug_user_check_id(1), True)
        self.assertEqual(permchecks.debug_user_check_id(4), True)


if __name__ == '__main__':
    unittest.main()
