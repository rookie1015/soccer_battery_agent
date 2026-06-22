import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from football_lottery_agent.history import archive_report, render_history_index


class HistoryTests(unittest.TestCase):
    def test_archive_report_keeps_latest_52_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "report.html"
            markdown = root / "report.md"
            html.write_text("<html>report</html>", encoding="utf-8")
            markdown.write_text("# report", encoding="utf-8")
            base = datetime(2026, 1, 1, 12, 0, 0)

            for index in range(60):
                archive_report(
                    "analysis",
                    f"issue-{index}",
                    html,
                    markdown,
                    history_dir=root / "history",
                    created_at=base + timedelta(days=index),
                )

            entries = json.loads((root / "history" / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(len(entries), 52)
        self.assertEqual(entries[0]["issue"], "issue-59")
        self.assertEqual(entries[-1]["issue"], "issue-8")

    def test_render_history_index_contains_selector_and_iframe(self) -> None:
        html = render_history_index(
            [
                {
                    "id": "one",
                    "kind": "analysis",
                    "issue": "26087",
                    "title": "分析报告：26087",
                    "created_at": "2026-06-17T20:00:00",
                    "html": "items/one.html",
                    "markdown": "items/one.md",
                }
            ]
        )

        self.assertIn("选择历史报告", html)
        self.assertIn("<iframe", html)
        self.assertIn("items/one.html", html)
        self.assertIn("期号 26087", html)
        self.assertIn("查询时间：2026-06-17 20:00:00", html)

    def test_render_history_index_groups_all_queries_for_same_issue(self) -> None:
        entries = [
            {
                "id": str(index),
                "kind": "analysis",
                "issue": "26087",
                "title": "分析报告：26087",
                "created_at": f"2026-06-17T20:00:0{index}",
                "html": f"items/{index}.html",
                "markdown": "",
            }
            for index in range(2)
        ]

        html = render_history_index(entries)

        self.assertEqual(html.count("期号 26087"), 1)
        self.assertIn("2 次查询", html)
        self.assertIn("items/0.html", html)
        self.assertIn("items/1.html", html)


if __name__ == "__main__":
    unittest.main()
