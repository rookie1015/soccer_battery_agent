import unittest
from unittest.mock import patch

from football_lottery_agent.notifier import _trim_for_message, send_text


class NotifierTests(unittest.TestCase):
    def test_trim_short_message_keeps_text(self) -> None:
        self.assertEqual(_trim_for_message("hello", limit=20), "hello")

    def test_trim_long_message_adds_notice(self) -> None:
        text = _trim_for_message("a" * 100, limit=50)
        self.assertLessEqual(len(text), 50)
        self.assertIn("已截断", text)

    def test_send_text_builds_feishu_payload(self) -> None:
        with patch("football_lottery_agent.notifier._post_json", return_value='{"code":0}') as post_json:
            result = send_text("feishu", "预测完成", "https://example.test/webhook")

        self.assertEqual(result.channel, "feishu")
        self.assertEqual(post_json.call_args.args[1]["content"]["text"], "预测完成")


if __name__ == "__main__":
    unittest.main()
