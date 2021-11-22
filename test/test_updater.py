import unittest

from coreplugins.update import consume_digits, is_newer, is_equal


class TestUpdater(unittest.TestCase):
    """Tests the updater core plugin"""
    def test_updater_version_detection(self):
        """Test the version detection which version is newer"""

        self.assertEqual(consume_digits("123abc"), ("123", "", "base"))
        self.assertEqual(consume_digits("123-Abc4"), ("123", "-", "abc4"))
        self.assertEqual(consume_digits("-123"), ("", "-", "123"))
        self.assertEqual(consume_digits("abc4"), ("", "", "abc4"))
        self.assertEqual(consume_digits("123"), ("123", "", ""))

        self.assertTrue(is_newer("1.2.1", "1.2.0"))
        self.assertTrue(is_newer("1.1.0", "1.1.0a"))
        self.assertTrue(is_newer("1.2.a", "1.1.0"))
        self.assertFalse(is_newer("1.1.0", "1.1"))
        self.assertFalse(is_newer("1.1.0", "1.1.0"))
        self.assertFalse(is_newer("1.1.0a", "1.1.0"))
        self.assertFalse(is_newer("1.1.0a", "1.1.0b"))
        self.assertFalse(is_newer("1.1.0ab", "1.1.0a"))
        self.assertFalse(is_newer("1.1.a", "1.1.0"))
        self.assertFalse(is_newer("1.1a.0", "1.1.0"))

        self.assertTrue(is_equal("1.2.3", "1.2.3"))
        self.assertTrue(is_equal("1.2.0", "1.2"))
        self.assertTrue(is_equal("1.2", "1.2.0"))
        self.assertTrue(is_equal("1.1-a", "1.1a"))
        self.assertTrue(is_equal("1.a", "1.a"))
        self.assertTrue(is_equal("foo", "foo"))
        self.assertFalse(is_equal("1.1.0", "1.2.0"))
        self.assertFalse(is_equal("1.1.0", "1.1.1"))
        self.assertFalse(is_equal("1.1.1-a", "1.1.1"))


if __name__ == '__main__':
    unittest.main()
