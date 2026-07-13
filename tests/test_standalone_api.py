import tempfile
import unittest
from datetime import datetime, timedelta
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

    def test_analysis_can_use_full_mobile_mode(self) -> None:
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
                standalone_api.run_analysis({"issue": "26090", "full_analysis": True}, Path(tmp))

        self.assertFalse(collect_issue.call_args.kwargs["skip_context_fetches"])
        self.assertFalse(collect_issue.call_args.kwargs["sina_odds_only"])
        self.assertTrue(collect_issue.call_args.kwargs["strength_model"])
        self.assertFalse(collect_issue.call_args.kwargs["foreign_odds"])

    def test_analysis_passes_ticket_budget_to_strategy(self) -> None:
        fake_plan = Mock()
        fake_plan.issue.issue = "26090"
        fake_plan.issue.metadata = {}
        fake_plan.predictions = []
        fake_plan.choose9_keep = []
        fake_plan.choose9_drop = []
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue", return_value=Path(tmp) / "issue.json"),
                patch.object(standalone_api, "load_issue", return_value=Mock()) as load_issue,
                patch.object(standalone_api, "build_ticket_plan", return_value=fake_plan) as build_ticket_plan,
                patch.object(standalone_api, "write_report"),
                patch.object(standalone_api, "write_analysis_html"),
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html"),
            ):
                standalone_api.run_analysis({"issue": "26090", "max_ticket_cost_yuan": 288}, Path(tmp))

        build_ticket_plan.assert_called_once_with(load_issue.return_value, max_ticket_cost_yuan=288)

    def test_analysis_rejects_too_small_ticket_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "最高购彩金额不能低于 2 元"):
                standalone_api.run_analysis({"issue": "26090", "max_ticket_cost_yuan": 1}, Path(tmp))

    def test_full_analysis_uses_saved_foreign_odds_key(self) -> None:
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
                standalone_api.run_analysis(
                    {
                        "issue": "26090",
                        "full_analysis": True,
                        "foreign_odds_api_key": "odds-key",
                    },
                    Path(tmp),
                )

        self.assertTrue(collect_issue.call_args.kwargs["foreign_odds"])
        self.assertEqual(collect_issue.call_args.kwargs["foreign_odds_api_key"], "odds-key")

    def test_analysis_passes_foreign_odds_options(self) -> None:
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
                standalone_api.run_analysis(
                    {
                        "issue": "26090",
                        "foreign_odds": True,
                        "foreign_odds_api_key": "odds-key",
                    },
                    Path(tmp),
                )

        self.assertTrue(collect_issue.call_args.kwargs["foreign_odds"])
        self.assertEqual(collect_issue.call_args.kwargs["foreign_odds_api_key"], "odds-key")

    def test_review_uses_latest_analysis_report_recommendations(self) -> None:
        issue = "sample-001"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / f"{issue}_issue.json").write_text(
                Path("data/sample_issue.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            history_dir = root / "reports" / "history"
            html = root / "analysis.html"
            html.write_text("<h1>analysis</h1>", encoding="utf-8")
            old_markdown = root / "old.md"
            latest_markdown = root / "latest.md"
            old_markdown.write_text(_analysis_markdown(issue, "3", tuple(range(1, 10))), encoding="utf-8")
            latest_markdown.write_text(_analysis_markdown(issue, "0", tuple(range(6, 15))), encoding="utf-8")
            created = datetime(2026, 7, 13, 10, 0, 0)
            archive_report("analysis", issue, html, old_markdown, history_dir=history_dir, created_at=created)
            archive_report(
                "analysis",
                issue,
                html,
                latest_markdown,
                history_dir=history_dir,
                created_at=created + timedelta(seconds=1),
            )

            results_csv = "seq,score\n" + "\n".join(f"{seq},0-1" for seq in range(1, 15))
            result = standalone_api.run_review(
                {"issue": issue, "auto_results": False, "results_csv": results_csv},
                root,
            )

        predictions = result["report"]["predictions"]
        self.assertTrue(all(item["pick_text"] == "0" for item in predictions))
        self.assertEqual(result["report"]["choose9_keep"], list(range(6, 15)))
        self.assertEqual(result["report"]["metrics"]["low_risk_count"], 14)

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

    def test_history_parses_markdown_report_for_android_cards(self) -> None:
        markdown_text = """# 足球彩票分析报告：26090

## 任九建议

- 建议保留：1、2、3、4、5、6、7、8、9
- 建议剔除：10、11、12、13、14

## 14场逐场建议

| 序号 | 联赛 | 对阵 | 推荐 | 比分倾向 | 置信度 | 风险 | 概率(3/1/0) |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| 1 | 世界杯 | 甲队 vs 乙队 | 3/1 | 1-0 13%，1-1 12%，2-0 10% | 53.0% | 中 | 53%/25%/22% |

## 详细理由

### 1. 甲队 vs 乙队

- 比赛：世界杯，2026-07-06T20:00:00+08:00
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.html"
            markdown = root / "report.md"
            report.write_text("<h1>report</h1>", encoding="utf-8")
            markdown.write_text(markdown_text, encoding="utf-8")
            archive_report("analysis", "26090", report, markdown, history_dir=root / "reports" / "history")

            result = standalone_api.run_history(root)

        parsed = result["entries"][0]["report"]
        self.assertEqual(parsed["issue"], "26090")
        self.assertEqual(parsed["metrics"]["match_count"], 1)
        self.assertEqual(parsed["choose9_drop"], [10, 11, 12, 13, 14])
        self.assertEqual(parsed["predictions"][0]["pick_labels"], ["主胜", "平"])
        self.assertEqual(parsed["predictions"][0]["kickoff_display"], "07-06 20:00")

    def test_history_parses_review_keep_rows_for_android_summary(self) -> None:
        markdown_text = """# 足球彩票复盘报告：26090

## 总览

- 胜平负命中：1/2（50%）
- 单选命中：1/1（100%）

## 逐场复盘

| 序号 | 对阵 | 最终比分 | 彩果 | 推荐 | 胜平负 | 比分预测 | 任九 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 甲队 vs 乙队 | 1-0 | 主胜 | 3 | 命中 | 1-0 13%，1-1 12% | 任九保留 |
| 2 | 丙队 vs 丁队 | 0-1 | 客胜 | 3 | 未中 | 1-0 10%，0-1 9% | 任九剔除 |
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "review.html"
            markdown = root / "review.md"
            report.write_text("<h1>review</h1>", encoding="utf-8")
            markdown.write_text(markdown_text, encoding="utf-8")
            archive_report("review", "26090", report, markdown, history_dir=root / "reports" / "history")

            result = standalone_api.run_history(root)

        parsed = result["entries"][0]["report"]
        self.assertEqual(parsed["purchase_deadline_source"], "复盘报告")
        self.assertEqual(parsed["choose9_keep"], [1])
        self.assertEqual(parsed["choose9_drop"], [2])
        self.assertTrue(parsed["predictions"][0]["outcome_hit"])
        self.assertEqual(parsed["predictions"][0]["final_result_label"], "主胜")


if __name__ == "__main__":
    unittest.main()


def _analysis_markdown(issue: str, pick: str, keep: tuple[int, ...]) -> str:
    drop = tuple(seq for seq in range(1, 15) if seq not in keep)
    rows = "\n".join(
        f"| {seq} | 测试联赛 | 主队{seq} vs 客队{seq} | {pick} | 1-0 13% | 53.0% | 中 | 53%/25%/22% |"
        for seq in range(1, 15)
    )
    return f"""# 足球彩票分析报告：{issue}

## 任九建议

- 建议保留：{'、'.join(str(seq) for seq in keep)}
- 建议剔除：{'、'.join(str(seq) for seq in drop)}

## 14场逐场建议

| 序号 | 联赛 | 对阵 | 推荐 | 比分倾向 | 置信度 | 风险 | 概率(3/1/0) |
| --- | --- | --- | --- | --- | ---: | --- | --- |
{rows}
"""
