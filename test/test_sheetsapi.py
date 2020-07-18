import unittest

import Geckarbot
from conf import Config
from botutils import sheetsclient


class SheetsApiTestCase(unittest.TestCase):
    def setUp(self):
        Config().load_bot()
        Geckarbot.logging_setup()

    def test_get(self):
        # only for current state of sheets as of 2020-07-18 12:00 pm
        c = sheetsclient.Client("1mSDrTqdcOSOuvR9Y9hMzuEx1X9puaUVuqs7yp6Ju6_M")
        v = c.get("Archiv!C6")
        self.assertEqual(v['values'][0][0], "Chr1s")

        c = sheetsclient.Client("1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8")
        v = c.get("B4")
        self.assertEqual(v['values'][0][0], "User")

        c = sheetsclient.Client("1HH42s5DX4FbuEeJPdm8l1TK70o2_EKADNOLkhu5qRa8")
        v = c.get("Hall of Fame!B4:D13")
        self.assertEqual(v['values'][4][1], "Splitt13")


if __name__ == '__main__':
    unittest.main()
