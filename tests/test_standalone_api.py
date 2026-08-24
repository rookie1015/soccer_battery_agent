import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from football_lottery_agent import standalone_api
from football_lottery_agent.history import archive_report, load_history_entries
from football_lottery_agent.loader import load_issue
from football_lottery_agent.notifier import NotifyResult
from football_lottery_agent.report import render_markdown
from football_lottery_agent.strategy import build_ticket_plan


class StandaloneApiTests(unittest.TestCase):
    def test_recent_full_snapshot_is_reused_for_immediate_repeat(self) -> None:
        now = datetime.now().astimezone()
        snapshot = {
            "issue": "26090",
            "metadata": {
                "analysis_mode": "full",
                "snapshot_collected_at": now.isoformat(),
                "foreign_odds_audit": {"configured": False},
            },
            "matches": [{"seq": seq} for seq in range(1, 15)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive.json"
            output = root / "collected.json"
            archive.write_text(json.dumps(snapshot), encoding="utf-8")

            reused = standalone_api._reuse_recent_issue_snapshot(
                archive,
                output,
                issue="26090",
                foreign_odds_configured=False,
                now=now,
            )
            copied = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(reused)
        self.assertTrue(copied["metadata"]["snapshot_reused"])
        self.assertEqual(copied["metadata"]["snapshot_reuse_age_seconds"], 0.0)

    def test_stale_or_differently_configured_snapshot_is_not_reused(self) -> None:
        now = datetime.now().astimezone()
        snapshot = {
            "issue": "26090",
            "metadata": {
                "analysis_mode": "full",
                "snapshot_collected_at": (now - timedelta(minutes=4)).isoformat(),
                "foreign_odds_audit": {"configured": False},
            },
            "matches": [{"seq": seq} for seq in range(1, 15)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive.json"
            output = root / "collected.json"
            archive.write_text(json.dumps(snapshot), encoding="utf-8")

            stale = standalone_api._reuse_recent_issue_snapshot(
                archive, output, issue="26090", foreign_odds_configured=False, now=now
            )
            snapshot["metadata"]["snapshot_collected_at"] = now.isoformat()
            archive.write_text(json.dumps(snapshot), encoding="utf-8")
            mismatched = standalone_api._reuse_recent_issue_snapshot(
                archive, output, issue="26090", foreign_odds_configured=True, now=now
            )

        self.assertFalse(stale)
        self.assertFalse(mismatched)

    def test_send_feishu_accepts_success_response(self) -> None:
        with patch.object(
            standalone_api,
            "send_text",
            return_value=NotifyResult(channel="feishu", response_text='{"code":0,"msg":"success"}'),
        ) as send_text:
            result = standalone_api.run_send_feishu(
                {
                    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
                    "text": "第 26090 期出票建议",
                }
            )

        self.assertTrue(result["ok"])
        send_text.assert_called_once_with(
            "feishu",
            "第 26090 期出票建议",
            "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        )

    def test_send_feishu_surfaces_bot_rejection(self) -> None:
        with patch.object(
            standalone_api,
            "send_text",
            return_value=NotifyResult(channel="feishu", response_text='{"code":19024,"msg":"Key Words Not Found"}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "19024"):
                standalone_api.run_send_feishu(
                    {
                        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
                        "text": "测试消息",
                    }
                )

    def test_send_feishu_rejects_non_feishu_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "自定义机器人"):
            standalone_api.run_send_feishu(
                {"webhook_url": "https://example.com/hook", "text": "测试消息"}
            )

    def test_health_reports_local_service(self) -> None:
        self.assertEqual(
            standalone_api.run_health(),
            {"ok": True, "service": "football-lottery-agent-local"},
        )

    def test_foreign_odds_usage_returns_provider_status(self) -> None:
        usage = {"status": "valid", "credits_remaining": 488, "credits_used": 12}
        with patch("football_lottery_agent.foreign_odds.check_the_odds_api_usage", return_value=usage) as check:
            result = standalone_api.run_foreign_odds_usage({"foreign_odds_api_key": "saved-key"})

        check.assert_called_once_with("saved-key")
        self.assertTrue(result["ok"])
        self.assertEqual(result["usage"], usage)

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

    def test_analysis_defaults_to_full_mode_with_fixed_twenty_match_sample(self) -> None:
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

        self.assertFalse(collect_issue.call_args.kwargs["skip_context_fetches"])
        self.assertFalse(collect_issue.call_args.kwargs["sina_odds_only"])
        self.assertTrue(collect_issue.call_args.kwargs["strength_model"])
        self.assertEqual(collect_issue.call_args.kwargs["strength_xg_matches"], 20)

    def test_analysis_rejects_malformed_issue_before_network_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue") as collect_issue,
                self.assertRaisesRegex(
                    standalone_api.AnalysisUserError,
                    "期号格式不正确，请输入 5 位数字",
                ),
            ):
                standalone_api.run_analysis({"issue": "abc"}, Path(tmp))

        collect_issue.assert_not_called()

    def test_analysis_rejects_impossible_issue_before_network_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue") as collect_issue,
                self.assertRaisesRegex(
                    standalone_api.AnalysisUserError,
                    "第 99999 期不存在，请检查期号后重试",
                ),
            ):
                standalone_api.run_analysis({"issue": "99999"}, Path(tmp))

        collect_issue.assert_not_called()

    def test_analysis_reports_requested_issue_when_schedule_provider_returns_another_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(
                    standalone_api,
                    "collect_issue",
                    side_effect=ValueError("Sina returned issue 26104 when issue 26105 was requested."),
                ),
                self.assertRaisesRegex(
                    standalone_api.AnalysisUserError,
                    "没有找到第 26105 期，请检查期号是否正确",
                ),
            ):
                standalone_api.run_analysis({"issue": "26105"}, Path(tmp))

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
                patch.object(standalone_api, "build_ticket_plan", return_value=fake_plan) as build_ticket_plan,
                patch.object(standalone_api, "write_report"),
                patch.object(standalone_api, "write_analysis_html"),
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html"),
            ):
                standalone_api.run_analysis({"issue": "26090", "full_analysis": True}, Path(tmp))

        self.assertFalse(collect_issue.call_args.kwargs["skip_context_fetches"])
        self.assertFalse(collect_issue.call_args.kwargs["sina_odds_only"])
        self.assertTrue(collect_issue.call_args.kwargs["strength_model"])
        self.assertFalse(collect_issue.call_args.kwargs["foreign_odds"])
        self.assertTrue(build_ticket_plan.call_args.kwargs["evidence_aware_secondary"])

    def test_analysis_stops_when_full_sources_have_broad_network_failures(self) -> None:
        def fake_collect(**kwargs: object) -> Path:
            output_path = Path(str(kwargs["output_path"]))
            failed_source = {"status": "request_failed"}
            matches = [
                {
                    "seq": seq,
                    "sources": {
                        "collection_audit": {
                            "injuries": failed_source,
                            "history": failed_source,
                            "intelligence": failed_source,
                            "odds_movement": failed_source,
                            "asian_handicap": failed_source,
                        }
                    }
                }
                for seq in range(1, 15)
            ]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps({"issue": "26090", "metadata": {}, "matches": matches}),
                encoding="utf-8",
            )
            return output_path

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue", side_effect=fake_collect) as collect_issue,
                patch.object(standalone_api, "write_report") as write_report,
                patch.object(standalone_api, "archive_report") as archive_report,
                self.assertRaises(standalone_api.AnalysisUserError) as raised,
            ):
                standalone_api.run_analysis({"issue": "26090"}, Path(tmp))

        self.assertEqual(collect_issue.call_count, 1)
        self.assertFalse(collect_issue.call_args.kwargs["skip_context_fetches"])
        self.assertFalse(collect_issue.call_args.kwargs["sina_odds_only"])
        self.assertIn("多个关键资料源大范围不可用", str(raised.exception))
        self.assertIn("伤停信息", str(raised.exception))
        self.assertIn("本次未生成分析报告", str(raised.exception))
        write_report.assert_not_called()
        archive_report.assert_not_called()

    def test_analysis_error_message_hides_internal_exception_details(self) -> None:
        message = standalone_api.analysis_error_message(
            RuntimeError("Traceback: secret.py line 42 INTERNAL_ERROR_CODE")
        )

        self.assertTrue(message.startswith("完整分析失败："))
        self.assertNotIn("Traceback", message)
        self.assertNotIn("secret.py", message)
        self.assertNotIn("INTERNAL_ERROR_CODE", message)

    def test_analysis_collection_error_is_converted_to_chinese_user_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue", side_effect=TimeoutError("socket timeout 120")),
                self.assertRaisesRegex(
                    standalone_api.AnalysisUserError,
                    "连接数据源超时，请检查网络后重试",
                ),
            ):
                standalone_api.run_analysis({"issue": "26090"}, Path(tmp))

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
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html") as archive_report,
            ):
                standalone_api.run_analysis({"issue": "26090", "max_ticket_cost_yuan": 288}, Path(tmp))

        build_ticket_plan.assert_called_once_with(
            load_issue.return_value,
            max_ticket_cost_yuan=288,
            evidence_aware_secondary=True,
        )
        self.assertEqual(
            archive_report.call_args.kwargs["condition_key"],
            "analysis|issue=26090|max_ticket_cost_yuan=288",
        )

    def test_analysis_uses_only_gate_approved_active_weights(self) -> None:
        fake_plan = Mock()
        fake_plan.issue.issue = "26090"
        fake_plan.issue.metadata = {}
        fake_plan.predictions = []
        fake_plan.choose9_keep = []
        fake_plan.choose9_drop = []
        active_weights = {"odds": 0.4, "signals": 0.2, "dixon_coles": 0.4}
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue"),
                patch.object(standalone_api, "build_calibration", return_value={
                    "status": "calibrated",
                    "sample_count": 140,
                    "minimum_samples": 84,
                    "weights": {"odds": 0.9, "signals": 0.1, "dixon_coles": 0.0},
                }),
                patch.object(standalone_api, "load_active_model_weights", return_value=active_weights),
                patch.object(standalone_api, "load_issue", return_value=Mock()) as load_issue,
                patch.object(standalone_api, "build_ticket_plan", return_value=fake_plan) as build_ticket_plan,
                patch.object(standalone_api, "write_report"),
                patch.object(standalone_api, "write_analysis_html"),
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html"),
            ):
                result = standalone_api.run_analysis(
                    {"issue": "26090", "max_ticket_cost_yuan": 288},
                    Path(tmp),
                )

        build_ticket_plan.assert_called_once_with(
            load_issue.return_value,
            max_ticket_cost_yuan=288,
            model_weights=active_weights,
            evidence_aware_secondary=True,
        )
        self.assertEqual(result["report"]["model_calibration"]["status"], "experiment_active")

    def test_analysis_does_not_use_ungated_calibration_weights(self) -> None:
        fake_plan = Mock()
        fake_plan.issue.issue = "26090"
        fake_plan.issue.metadata = {}
        fake_plan.predictions = []
        fake_plan.choose9_keep = []
        fake_plan.choose9_drop = []
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(standalone_api, "collect_issue"),
                patch.object(standalone_api, "build_calibration", return_value={
                    "status": "calibrated",
                    "sample_count": 140,
                    "minimum_samples": 84,
                    "weights": {"odds": 0.9, "signals": 0.1, "dixon_coles": 0.0},
                }),
                patch.object(standalone_api, "load_active_model_weights", return_value=None),
                patch.object(standalone_api, "load_issue", return_value=Mock()) as load_issue,
                patch.object(standalone_api, "build_ticket_plan", return_value=fake_plan) as build_ticket_plan,
                patch.object(standalone_api, "write_report"),
                patch.object(standalone_api, "write_analysis_html"),
                patch.object(standalone_api, "archive_report", return_value=Path(tmp) / "history.html"),
            ):
                result = standalone_api.run_analysis(
                    {"issue": "26090", "max_ticket_cost_yuan": 288},
                    Path(tmp),
                )

        build_ticket_plan.assert_called_once_with(
            load_issue.return_value,
            max_ticket_cost_yuan=288,
            evidence_aware_secondary=True,
        )
        self.assertEqual(result["report"]["model_calibration"]["status"], "experiment_pending_gate")

    def test_analysis_rejects_too_small_ticket_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "最高购彩金额不能低于 2 元"):
                standalone_api.run_analysis({"issue": "26090", "max_ticket_cost_yuan": 1}, Path(tmp))

    def test_analysis_honors_cancellation_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel_path = root / "cache" / "analysis_cancel_request-1.flag"
            cancel_path.parent.mkdir(parents=True)
            cancel_path.write_text("cancel", encoding="utf-8")
            with (
                patch.object(standalone_api, "collect_issue") as collect_issue,
                patch.object(standalone_api, "write_report") as write_report,
                patch.object(standalone_api, "archive_report") as archive_report,
                self.assertRaisesRegex(standalone_api.AnalysisCancelledError, "分析已取消"),
            ):
                standalone_api.run_analysis(
                    {"issue": "26090", "cancel_token": "request-1"},
                    root,
                )

            collect_issue.assert_not_called()
            write_report.assert_not_called()
            archive_report.assert_not_called()
            self.assertFalse(cancel_path.exists())

    def test_analysis_cancelled_during_collection_does_not_write_reports_or_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel_path = root / "cache" / "analysis_cancel_request-2.flag"

            def fake_collect(**kwargs: object) -> Path:
                cancel_path.parent.mkdir(parents=True, exist_ok=True)
                cancel_path.write_text("cancel", encoding="utf-8")
                kwargs["cancel_check"]()
                return root / "data" / "collected_issue.json"

            with (
                patch.object(standalone_api, "collect_issue", side_effect=fake_collect),
                patch.object(standalone_api, "write_report") as write_report,
                patch.object(standalone_api, "write_analysis_html") as write_analysis_html,
                patch.object(standalone_api, "archive_report") as archive_report,
                self.assertRaisesRegex(standalone_api.AnalysisCancelledError, "分析已取消"),
            ):
                standalone_api.run_analysis(
                    {"issue": "26090", "cancel_token": "request-2"},
                    root,
                )

            write_report.assert_not_called()
            write_analysis_html.assert_not_called()
            archive_report.assert_not_called()
            self.assertFalse(cancel_path.exists())

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

    def test_review_uses_selected_analysis_report_recommendations(self) -> None:
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

            results_csv = "seq,score\n" + "\n".join(f"{seq},1-0" for seq in range(1, 15))
            older_analysis_id = load_history_entries(history_dir)[-1]["id"]
            result = standalone_api.run_review(
                {
                    "issue": issue,
                    "analysis_id": older_analysis_id,
                    "auto_results": False,
                    "results_csv": results_csv,
                },
                root,
            )

        predictions = result["report"]["predictions"]
        self.assertTrue(all(item["pick_text"] == "3" for item in predictions))
        self.assertEqual(result["report"]["choose9_keep"], list(range(1, 10)))
        self.assertEqual(result["report"]["metrics"]["low_risk_count"], 14)

    def test_review_requires_selection_when_issue_has_multiple_analyses(self) -> None:
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
            markdown = root / "analysis.md"
            html.write_text("<h1>analysis</h1>", encoding="utf-8")
            markdown.write_text(_analysis_markdown(issue, "3", tuple(range(1, 10))), encoding="utf-8")
            created = datetime(2026, 7, 13, 10, 0, 0)
            archive_report("analysis", issue, html, markdown, history_dir=history_dir, created_at=created)
            archive_report(
                "analysis",
                issue,
                html,
                markdown,
                history_dir=history_dir,
                created_at=created + timedelta(seconds=1),
            )

            results_csv = "seq,score\n" + "\n".join(f"{seq},1-0" for seq in range(1, 15))
            with self.assertRaisesRegex(ValueError, "发现 2 次分析结果"):
                standalone_api.run_review(
                    {"issue": issue, "auto_results": False, "results_csv": results_csv},
                    root,
                )

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

    def test_delete_history_only_removes_analysis_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_dir = root / "reports" / "history"
            report = root / "report.html"
            markdown = root / "report.md"
            report.write_text("<h1>report</h1>", encoding="utf-8")
            markdown.write_text("# report", encoding="utf-8")
            archive_report("analysis", "26100", report, markdown, history_dir=history_dir)
            archive_report("review", "26100", report, markdown, history_dir=history_dir)
            entries = load_history_entries(history_dir)
            analysis = next(item for item in entries if item["kind"] == "analysis")
            review = next(item for item in entries if item["kind"] == "review")

            result = standalone_api.run_delete_history(
                {"entry_ids": [analysis["id"], review["id"]]},
                root,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual([item["kind"] for item in load_history_entries(history_dir)], ["review"])

    def test_history_parses_markdown_report_for_android_cards(self) -> None:
        markdown_text = """# 足球彩票分析报告：26090

## 任九建议

- 建议保留：1、2、3、4、5、6、7、8、9
- 建议剔除：10、11、12、13、14

## 14场逐场建议

| 序号 | 联赛 | 对阵 | 推荐 | 比分倾向 | 置信度 | 风险 | 概率(3/1/0) |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| 1 | 世界杯 | 甲队 vs 乙队 | 3/1/0 | 1-0 13%，1-1 12%，2-0 10% | 39.0% | 高 | 39%/31%/30% |

## 详细理由

### 1. 甲队 vs 乙队

- 比赛：世界杯，2026-07-06T20:00:00+08:00
- 推荐：`3/1/0`（主胜 / 平 / 客胜）
- 风险：高
- 综合赔率和基本面，主胜最高，约 39%；次选平约 31%。
- 情报：双方近期状态接近，任一结果都不能轻易排除。
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
        self.assertEqual(parsed["predictions"][0]["pick_labels"], ["主胜", "平", "客胜"])
        self.assertEqual(parsed["predictions"][0]["kickoff_display"], "07-06 20:00")
        reasons = parsed["predictions"][0]["reasons"]
        self.assertIn("3/1/0 全包", reasons[0])
        self.assertIn("没有足够把握排除任何一项", reasons[0])
        self.assertIn("综合赔率和基本面", reasons[1])
        self.assertIn("双方近期状态接近", reasons[2])
        self.assertTrue(all(not reason.startswith("比赛：") for reason in reasons))

    def test_history_parser_supports_separate_model_and_budget_selections(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"), max_ticket_cost_yuan=128)

        parsed = standalone_api._parse_history_report(
            render_markdown(plan),
            plan.issue.issue,
            "analysis",
        )

        self.assertIsNotNone(parsed)
        first = parsed["predictions"][0]
        self.assertEqual(first["analysis_pick_text"], plan.predictions[0].analysis_pick_text)
        self.assertEqual(first["pick_text"], plan.predictions[0].pick_text)
        self.assertEqual(first["budget_adjusted"], plan.predictions[0].budget_adjusted)
        self.assertEqual(len(parsed["predictions"]), 14)
        self.assertEqual(parsed["budget"]["total_cost_yuan"], 128)
        self.assertEqual(parsed["metrics"]["line_portfolio_count"], 0)
        self.assertIsNone(parsed["line_portfolio"])

    def test_history_parses_purchase_deadline_from_new_markdown(self) -> None:
        markdown_text = _analysis_markdown("26095", "3", tuple(range(1, 10))).replace(
            "## 任九建议",
            "## 期次信息\n\n"
            "- 购彩截止时间：2026-07-25 20:30:00\n"
            "- 截止时间来源：中国体彩网官方\n"
            "- 开售时间：2026-07-22 20:00:00\n\n"
            "## 任九建议",
        )
        parsed = standalone_api._parse_history_report(markdown_text, "26095", "analysis")

        self.assertEqual(parsed["purchase_deadline"], "2026-07-25 20:30:00")
        self.assertEqual(parsed["purchase_deadline_source"], "中国体彩网官方")
        self.assertEqual(parsed["sale_begin_time"], "2026-07-22 20:00:00")

    def test_history_restores_deadline_for_old_markdown_from_archived_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            issue_data = json.loads(Path("data/sample_issue.json").read_text(encoding="utf-8"))
            issue_data["issue"] = "26090"
            issue_data["metadata"] = {
                "purchase_deadline": "2026-07-04 23:00:00",
                "purchase_deadline_source": "中国体彩网官方",
                "sale_begin_time": "2026-07-04 18:00:00",
            }
            data_dir = root / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "26090_issue.json").write_text(
                json.dumps(issue_data, ensure_ascii=False),
                encoding="utf-8",
            )
            report = root / "report.html"
            markdown = root / "report.md"
            report.write_text("<h1>report</h1>", encoding="utf-8")
            markdown.write_text(
                _analysis_markdown("26090", "3", tuple(range(1, 10))),
                encoding="utf-8",
            )
            archive_report("analysis", "26090", report, markdown, history_dir=root / "reports" / "history")

            result = standalone_api.run_history(root)

        parsed = result["entries"][0]["report"]
        self.assertEqual(parsed["purchase_deadline"], "2026-07-04 23:00:00")
        self.assertEqual(parsed["purchase_deadline_source"], "中国体彩网官方")

    def test_history_parses_review_keep_rows_for_android_summary(self) -> None:
        markdown_text = """# 足球彩票复盘报告：26090

## 总览

- 胜平负命中：1/2（50%）
- 单选命中：1/1（100%）

## 逐场复盘

| 序号 | 对阵 | 最终比分 | 彩果 | 推荐 | 胜平负 | 比分预测 | 任九 | 错因标签 | 赛后外部线索 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 甲队 vs 乙队 | 1-0 | 主胜 | 模型 3/1/0 → 预算 3/0 | 命中 | 1-0 13%，1-1 12% | 任九保留 | - | - |
| 2 | 丙队 vs 丁队 | 0-1 | 客胜 | 3 | 未中 | 1-0 10%，0-1 9% | 任九剔除 | 平局漏判、单选覆盖不足 | 关键伤停或临场阵容变化 |
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
        self.assertEqual(parsed["predictions"][1]["diagnostic_tags"], ["平局漏判", "单选覆盖不足"])
        self.assertEqual(parsed["predictions"][1]["post_match_evidence"][0]["label"], "关键伤停或临场阵容变化")
        self.assertTrue(parsed["predictions"][0]["outcome_hit"])
        self.assertEqual(parsed["predictions"][0]["final_result_label"], "主胜")
        self.assertEqual(parsed["predictions"][0]["analysis_pick_text"], "3/1/0")
        self.assertEqual(parsed["predictions"][0]["pick_text"], "3/0")
        self.assertTrue(parsed["predictions"][0]["budget_adjusted"])


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
