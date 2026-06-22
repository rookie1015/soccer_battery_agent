import unittest

from football_lottery_agent.loader import load_issue
from football_lottery_agent.report import render_markdown
from football_lottery_agent.strategy import build_ticket_plan


class StrategyTests(unittest.TestCase):
    def test_build_ticket_plan_has_14_predictions(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)

        self.assertEqual(len(plan.predictions), 14)
        self.assertEqual(len(plan.choose9_keep), 9)
        self.assertEqual(len(plan.choose9_drop), 5)
        self.assertTrue(set(plan.choose9_keep).isdisjoint(plan.choose9_drop))

    def test_predictions_include_scorelines(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        prediction = plan.predictions[0]

        self.assertEqual(len(prediction.scorelines), 3)
        self.assertGreater(prediction.scorelines[0].probability, 0)
        self.assertGreaterEqual(prediction.scorelines[0].probability, prediction.scorelines[1].probability)

    def test_report_renders_scoreline_summary(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        report = render_markdown(plan)

        self.assertIn("比分倾向", report)
        self.assertRegex(report, r"\d-\d \d+%")


if __name__ == "__main__":
    unittest.main()
