import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from football_lottery_agent import standalone_api
from football_lottery_agent.history import archive_report


class StandaloneApiTests(unittest.TestCase):
    def test_health_reports_local_service(self) -> None:
        self.assertEqual(
            standalone_api.run_health(),
            {"ok": True, "service": "football-lottery-agent-local"},
        )

    def test_single_prediction_accepts_manual_odds_without_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = standalone_api.run_single_prediction(
                {
                    "home": "甲队",
                    "away": "乙队",
                    "home_odds": "1.80",
                    "draw_odds": "3.40",
                    "away_odds": "4.20",
                },
                Path(tmp),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["home"], "甲队")
        self.assertEqual(result["away"], "乙队")
        self.assertEqual(len(result["scorelines"]), 3)
        self.assertIn("手工填写", result["data_source"])

    def test_analysis_uses_sina_odds_only_fast_mode(self) -> None:
        fake_plan = Mock()
        fake_plan.issue.issue = "26090"
        fake_plan.issue.metadata = {}
        fake_plan.predictions = []
        fake_plan.choose9_keep = []
        fake_plan.choose9_drop = []
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue", return_value=Path(tmp) / "issue.json") as collect_issue,
                patch.object(standalone_api, "load_issue", return_value=Mock()),
                patch.object(standalone_api, "build_ticket_plan", return_value=fake_plan),
                patch.object(standalone_api, "write_report"),
                patch.object(standalone_api, "write_analysis_html"),
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html"),
            ):
                standalone_api.run_analysis({"issue": "26090"}, Path(tmp))

        self.assertTrue(collect_issue.call_args.kwargs["skip_context_fetches"])
        self.assertTrue(collect_issue.call_args.kwargs["sina_odds_only"])
        self.assertFalse(collect_issue.call_args.kwargs["strength_model"])

    def test_history_returns_markdown_text_for_android_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.html"
            markdown = root / "report.md"
            report.write_text("<h1>report</h1>", encoding="utf-8")
            markdown.write_text("# analysis\n\npick: home", encoding="utf-8")
            archive_report("analysis", "26090", report, markdown, history_dir=root / "reports" / "history")

            result = standalone_api.run_history(root)

        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"][0]["issue"], "26090")
        self.assertIn("pick: home", result["entries"][0]["markdown_text"])


if __name__ == "__main__":
    unittest.main()
