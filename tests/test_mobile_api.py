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
        self.assertEqual(len(report["predictions"]), 14)

        first = report["predictions"][0]
        self.assertEqual(first["seq"], 1)
        self.assertIn("home", first["probabilities"])
        self.assertIn("score", first["scorelines"][0])
        self.assertIn("pick_labels", first)


if __name__ == "__main__":
    unittest.main()
