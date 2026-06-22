import unittest

from football_lottery_agent.notifier import _trim_for_message


class NotifierTests(unittest.TestCase):
    def test_trim_short_message_keeps_text(self) -> None:
        self.assertEqual(_trim_for_message("hello", limit=20), "hello")

    def test_trim_long_message_adds_notice(self) -> None:
        text = _trim_for_message("a" * 100, limit=50)
        self.assertLessEqual(len(text), 50)
        self.assertIn("已截断", text)


if __name__ == "__main__":
    unittest.main()
