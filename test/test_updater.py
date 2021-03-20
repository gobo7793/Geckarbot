import unittest

from coreplugins.update import consume_digits, is_newer, is_equal


class TestUpdater(unittest.TestCase):
    """Tests the updater core plugin"""
    def test_updater_version_detection(self):
        """Test the version detection which version is newer"""

        assert consume_digits("123abc") == ("123", "", "abc")
        assert consume_digits("123-Abc4") == ("123", "-", "abc4")
        assert consume_digits("-123") == ("", "-", "123")
        assert consume_digits("abc4") == ("", "", "abc4")
        assert consume_digits("123") == ("123", "", "")

        assert is_newer("1.2.1", "1.2.0")
        assert is_newer("1.1.0", "1.1.0a")
        assert is_newer("1.2.a", "1.1.0")
        assert not is_newer("1.1.0", "1.1")
        assert not is_newer("1.1.0", "1.1.0")
        assert not is_newer("1.1.0a", "1.1.0")
        assert not is_newer("1.1.0a", "1.1.0b")
        assert not is_newer("1.1.0ab", "1.1.0a")
        assert not is_newer("1.1.a", "1.1.0")
        assert not is_newer("1.1a.0", "1.1.0")

        assert is_equal("1.2.3", "1.2.3")
        assert is_equal("1.2.0", "1.2")
        assert is_equal("1.2", "1.2.0")
        assert is_equal("1.1-a", "1.1a")
        assert is_equal("1.a", "1.a")
        assert is_equal("foo", "foo")
        assert not is_equal("1.1.0", "1.2.0")
        assert not is_equal("1.1.0", "1.1.1")
        assert not is_equal("1.1.1-a", "1.1.1")


if __name__ == '__main__':
    unittest.main()
