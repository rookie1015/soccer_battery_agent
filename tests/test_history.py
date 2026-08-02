import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from football_lottery_agent.history import archive_report, load_history_entries, render_history_index, write_history_indexes


class HistoryTests(unittest.TestCase):
    def test_archive_report_copies_exact_analysis_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "report.html"
            snapshot = root / "issue.json"
            html.write_text("<html>report</html>", encoding="utf-8")
            snapshot.write_text('{"issue":"26098"}', encoding="utf-8")

            archive_report(
                "analysis",
                "26098",
                html,
                history_dir=root / "history",
                snapshot_path=snapshot,
                created_at=datetime(2026, 8, 2, 18, 0, 0),
            )
            entry = load_history_entries(root / "history")[0]
            copied = root / "history" / entry["snapshot"]

            self.assertTrue(copied.exists())
            self.assertEqual(copied.read_text(encoding="utf-8"), '{"issue":"26098"}')

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

    def test_render_history_index_activates_grouped_card_by_data_index(self) -> None:
        entries = [
            {
                "id": "review",
                "kind": "review",
                "issue": "26088",
                "title": "review",
                "created_at": "2026-06-30T22:50:00",
                "html": "items/review.html",
                "markdown": "",
            },
            {
                "id": "analysis",
                "kind": "analysis",
                "issue": "26089",
                "title": "analysis",
                "created_at": "2026-06-30T22:49:00",
                "html": "items/analysis.html",
                "markdown": "",
            },
        ]

        html = render_history_index(entries)

        self.assertIn('data-index="1"', html)
        self.assertIn('Number(card.dataset.index) === index', html)
        self.assertEqual(html.count('<details class="issue-group" open>'), 2)

    def test_archive_report_writes_separate_kind_history_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_html = root / "analysis-source.html"
            review_html = root / "review-source.html"
            analysis_html.write_text("<html>analysis</html>", encoding="utf-8")
            review_html.write_text("<html>review</html>", encoding="utf-8")

            analysis_path = archive_report("analysis", "26089", analysis_html, history_dir=root / "history")
            review_path = archive_report("review", "26088", review_html, history_dir=root / "history")

            analysis_page = (root / "history" / "analysis.html").read_text(encoding="utf-8")
            review_page = (root / "history" / "review.html").read_text(encoding="utf-8")

        self.assertEqual(analysis_path.name, "analysis.html")
        self.assertEqual(review_path.name, "review.html")
        self.assertIn("26089", analysis_page)
        self.assertNotIn("26088", analysis_page)
        self.assertIn("26088", review_page)
        self.assertNotIn("26089", review_page)

    def test_write_history_indexes_keeps_combined_and_kind_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [
                {
                    "id": "analysis",
                    "kind": "analysis",
                    "issue": "26089",
                    "title": "analysis",
                    "created_at": "2026-06-30T22:49:00",
                    "html": "items/analysis.html",
                    "markdown": "",
                },
                {
                    "id": "review",
                    "kind": "review",
                    "issue": "26088",
                    "title": "review",
                    "created_at": "2026-06-30T22:50:00",
                    "html": "items/review.html",
                    "markdown": "",
                },
            ]

            write_history_indexes(root / "history", entries)

            combined = (root / "history" / "index.html").read_text(encoding="utf-8")
            analysis = (root / "history" / "analysis.html").read_text(encoding="utf-8")
            review = (root / "history" / "review.html").read_text(encoding="utf-8")

        self.assertIn("26089", combined)
        self.assertIn("26088", combined)
        self.assertIn("26089", analysis)
        self.assertNotIn("26088", analysis)
        self.assertIn("26088", review)
        self.assertNotIn("26089", review)

    def test_load_history_entries_reads_index_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.json").write_text(
                json.dumps([{"id": "one", "kind": "analysis", "issue": "26090"}]),
                encoding="utf-8",
            )

            entries = load_history_entries(root)

        self.assertEqual(entries[0]["id"], "one")


if __name__ == "__main__":
    unittest.main()
