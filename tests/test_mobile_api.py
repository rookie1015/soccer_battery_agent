import unittest
from dataclasses import replace

from football_lottery_agent.loader import load_issue
from football_lottery_agent.mobile_api import serialize_ticket_plan
from football_lottery_agent.strategy import build_ticket_plan


class MobileApiTests(unittest.TestCase):
    def test_serialize_ticket_plan_returns_app_ready_report(self) -> None:
        issue = load_issue("data/sample_issue.json")
        issue = replace(
            issue,
            metadata={
                "purchase_deadline": "2026-07-04 23:00:00",
                "purchase_deadline_source": "中国体彩网官方接口",
            },
        )
        plan = build_ticket_plan(issue)

        report = serialize_ticket_plan(plan)

        self.assertEqual(report["issue"], "sample-001")
        self.assertEqual(report["purchase_deadline"], "2026-07-04 23:00:00")
        self.assertEqual(report["purchase_deadline_source"], "中国体彩网官方接口")
        self.assertEqual(report["metrics"]["match_count"], 14)
        self.assertEqual(len(report["choose9_keep"]), 9)
        self.assertEqual(len(report["choose9_drop"]), 5)
        self.assertEqual(report["choose9"]["mode"], "independent")
        self.assertEqual(report["choose9"]["budget_scope"], "separate")
        self.assertEqual(len(report["choose9"]["selections"]), 9)
        self.assertEqual(report["choose9"]["cost_yuan"], report["choose9"]["line_count"] * 2)
        self.assertLessEqual(report["choose9"]["cost_yuan"], report["choose9"]["limit_yuan"])
        self.assertEqual(len(report["predictions"]), 14)

        first = report["predictions"][0]
        self.assertEqual(first["seq"], 1)
        self.assertIn("home", first["probabilities"])
        self.assertNotIn("scorelines", first)
        self.assertNotIn("risk", first)
        self.assertIn("confidence", first)
        self.assertIn("pick_labels", first)
        self.assertIn("analysis_pick_text", first)
        self.assertIn("analysis_pick_labels", first)
        self.assertIn("budget_adjusted", first)
        self.assertIn("budget_forced_single", first)
        self.assertIn("draw_guard", first)
        self.assertIn("tactical_draw", first)
        self.assertIn("market_probabilities", first)
        self.assertIn("blend_weights", first)
        self.assertIn("fundamental_audit", first)
        self.assertIn("mathematical_corrections", first)
        self.assertIn("unused_yuan", report["budget"])
        self.assertIn("utilization_percent", report["budget"])
        self.assertIn("ticket_single_count", report["metrics"])
        self.assertIn("budget_forced_single_count", report["metrics"])
        self.assertIn("tactical_draw_count", report["metrics"])
        self.assertIn("draw_hedge_count", report["metrics"])
        self.assertIn("budget", report)
        self.assertLessEqual(report["budget"]["total_cost_yuan"], report["budget"]["limit_yuan"])
        self.assertIsNone(report["draw_hedge"])
        self.assertIsNone(report["line_portfolio"])
        expected_units = 1
        for prediction in report["predictions"]:
            expected_units *= len(prediction["pick_labels"])
        self.assertEqual(report["budget"]["total_cost_yuan"], expected_units * 2)


if __name__ == "__main__":
    unittest.main()
