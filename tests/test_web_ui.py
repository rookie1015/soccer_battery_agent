import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent import cli, web_ui
from football_lottery_agent.review import MatchResult, ResultsFetch
from football_lottery_agent.web_ui import render_ui


class WebUiTests(unittest.TestCase):
    def test_render_ui_contains_main_actions(self) -> None:
        html = render_ui()

        self.assertIn("足球彩票助手控制台", html)
        self.assertIn("生成分析报告", html)
        self.assertIn("生成复盘报告", html)
        self.assertIn("/api/analysis", html)
        self.assertIn("/api/review", html)
        self.assertIn("多来源自动拉取赛果", html)
        self.assertIn("单场比分预测", html)
        self.assertIn("/api/single-prediction", html)
        self.assertIn("每次生成后自动发送到飞书", html)
        self.assertIn("feishu_webhook", html)
        self.assertIn('id="singleHome" placeholder="例如：荷兰" autocomplete="off" required', html)
        self.assertIn('id="issue" value="26087" autocomplete="off" required', html)
        self.assertIn('id="reviewIssue" value="26087" autocomplete="off" required', html)
        self.assertIn("issue: document.getElementById(\"reviewIssue\").value.trim()", html)
        self.assertIn("validateSinglePrediction", html)
        self.assertIn("updateReviewMode", html)
        self.assertIn('].join("\\n");', html)

    def test_single_prediction_uses_collected_match_data(self) -> None:
        match = web_ui.Match(
            seq=1,
            kickoff=web_ui.datetime.now().astimezone(),
            league="测试联赛",
            home="荷兰",
            away="瑞典",
            odds=web_ui.Odds(home=1.80, draw=3.40, away=4.20),
            signals=web_ui.Signals(),
        )
        with patch.object(web_ui, "_find_collected_match", return_value=match):
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

    def test_single_prediction_rejects_partial_manual_odds(self) -> None:
        with self.assertRaisesRegex(ValueError, "欧赔请填写完整"):
            web_ui._run_single_prediction({"home": "甲队", "away": "乙队", "home_odds": "1.80"})

    def test_required_int_rejects_empty_and_out_of_range_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "请填写 xG 样本场次"):
            web_ui._parse_required_int(
                {"strength_xg_matches": ""},
                "strength_xg_matches",
                empty_message="请填写 xG 样本场次。",
                invalid_message="xG 样本场次必须是 0 到 20 之间的整数。",
                minimum=0,
                maximum=20,
            )
        with self.assertRaisesRegex(ValueError, "0 到 20"):
            web_ui._parse_required_int(
                {"strength_xg_matches": "21"},
                "strength_xg_matches",
                empty_message="请填写 xG 样本场次。",
                invalid_message="xG 样本场次必须是 0 到 20 之间的整数。",
                minimum=0,
                maximum=20,
            )

    def test_review_reports_missing_issue_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "请先生成赛前分析"):
            web_ui._run_review({"issue_path": "data/missing_issue.json"})

    def test_review_reports_missing_issue_number(self) -> None:
        with self.assertRaisesRegex(ValueError, "找不到 99999 的赛前数据"):
            web_ui._run_review({"issue": "99999"})

    def test_review_accepts_issue_number_from_current_issue_file(self) -> None:
        def exists(path: Path) -> bool:
            return str(path).replace("\\", "/") == "data/collected_issue.json"

        with (
            patch.object(web_ui.Path, "exists", exists),
            patch.object(web_ui, "load_issue", return_value=web_ui.load_issue("data/sample_issue.json")),
        ):
            self.assertEqual(
                web_ui._resolve_review_issue_path("sample-001", {}),
                Path("data/collected_issue.json"),
            )

    def test_review_fetches_results_for_requested_issue_number(self) -> None:
        issue = web_ui.load_issue("data/sample_issue.json")
        fetched = ResultsFetch(
            results={match.seq: MatchResult(match.seq, 1, 0, score_exact=False) for match in issue.matches},
            source="中国体彩网官方开奖",
        )
        with (
            patch.object(web_ui, "_resolve_review_issue_path", return_value=Path("data/sample_issue.json")),
            patch.object(web_ui, "fetch_results_with_fallbacks", return_value=fetched) as fetch_results,
            patch.object(web_ui, "write_review_report"),
            patch.object(web_ui, "write_review_html"),
            patch.object(web_ui, "archive_report", return_value=Path("reports/history/index.html")),
        ):
            result = web_ui._run_review({"issue": "sample-001", "auto_results": True})

        fetch_results.assert_called_once_with("sample-001")
        self.assertTrue(result["ok"])

    def test_review_removes_stale_outputs_when_auto_results_are_missing(self) -> None:
        markdown = Path("reports/sample-001_review.md")
        html = Path("reports/sample-001_review.html")
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text("stale", encoding="utf-8")
        html.write_text("stale", encoding="utf-8")

        with patch.object(web_ui, "fetch_results_with_fallbacks", return_value=ResultsFetch(results={}, source="中国体彩网官方开奖")):
            with self.assertRaisesRegex(ValueError, "多个赛果来源暂时都没有返回本期赛果"):
                web_ui._run_review({"issue_path": "data/sample_issue.json", "auto_results": True})

        self.assertFalse(markdown.exists())
        self.assertFalse(html.exists())

    def test_review_reports_empty_auto_results(self) -> None:
        with patch.object(web_ui, "fetch_results_with_fallbacks", return_value=ResultsFetch(results={}, source="测试源")):
            with self.assertRaisesRegex(ValueError, "多个赛果来源暂时都没有返回本期赛果"):
                web_ui._run_review({"issue_path": "data/sample_issue.json", "auto_results": True})

    def test_review_reports_incomplete_auto_results(self) -> None:
        fetched = ResultsFetch(results={1: MatchResult(1, 2, 1)}, source="测试源")
        with patch.object(web_ui, "fetch_results_with_fallbacks", return_value=fetched):
            with self.assertRaisesRegex(ValueError, "测试源 赛果还不完整"):
                web_ui._run_review({"issue_path": "data/sample_issue.json", "auto_results": True})

    def test_single_prediction_can_send_to_feishu(self) -> None:
        with patch.object(web_ui, "send_text") as send_text:
            result = web_ui._run_single_prediction(
                {
                    "home": "甲队",
                    "away": "乙队",
                    "send_feishu": True,
                    "feishu_webhook": "https://example.test/webhook",
                }
            )

        send_text.assert_called_once()
        self.assertIn("已发送到飞书", result["message"])

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
