import unittest

import Geckarbot
from botutils import sheetsclient


class SheetsApiTestCase(unittest.TestCase):
    """Tests for the sheets client"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = Geckarbot.Geckarbot()

    def setUp(self):
        Geckarbot.logging_setup()

    def test_get(self):
        """Tests getting cell data from sheet"""
        c = sheetsclient.Client(self.bot, "1rANJqqXmWiQ4CCfcc695uKBbsjqRpeghHw-AYDDkKM0")
        v = c.get("C3")
        self.assertEqual(v[0][0], "Hello, World")
        v = c.get("B3:B4")
        self.assertEqual(v, [["Hello"], ["World"]])
        v = c.get("Test1!C4")
        self.assertEqual(v[0][0], 5)


if __name__ == '__main__':
    unittest.main()
