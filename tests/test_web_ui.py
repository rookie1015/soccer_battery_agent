import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent import cli, web_ui
from football_lottery_agent.web_ui import render_ui


class WebUiTests(unittest.TestCase):
    def test_render_ui_contains_main_actions(self) -> None:
        html = render_ui()

        self.assertIn("足球彩票助手控制台", html)
        self.assertIn("生成分析报告", html)
        self.assertIn("生成复盘报告", html)
        self.assertIn("/api/analysis", html)
        self.assertIn("/api/review", html)
        self.assertIn("自动从新浪拉取赛果", html)
        self.assertIn("单场比分预测", html)
        self.assertIn("/api/single-prediction", html)

    def test_single_prediction_uses_collected_match_data(self) -> None:
        result = web_ui._run_single_prediction({"home": "荷兰", "away": "瑞典"})

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["scorelines"]), 3)
        self.assertIn("当前期已采集", result["data_source"])

    def test_single_prediction_accepts_manual_odds(self) -> None:
        result = web_ui._run_single_prediction(
            {"home": "甲队", "away": "乙队", "home_odds": "1.80", "draw_odds": "3.40", "away_odds": "4.20"}
        )

        self.assertTrue(result["ok"])
        self.assertIn("手工填写", result["data_source"])

    def test_cli_starts_ui(self) -> None:
        with (
            patch.object(sys, "argv", ["football-lottery-agent", "ui", "--port", "9876", "--no-open"]),
            patch.object(cli, "run_ui") as run_ui,
        ):
            cli.main()

        run_ui.assert_called_once_with(host="127.0.0.1", port=9876, open_browser=False)

    def test_start_ui_batch_exists(self) -> None:
        self.assertTrue(Path("start_ui.bat").exists())


if __name__ == "__main__":
    unittest.main()
