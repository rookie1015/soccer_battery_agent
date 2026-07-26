import unittest
from dataclasses import replace

from football_lottery_agent.loader import load_issue
from football_lottery_agent.report import render_markdown
from football_lottery_agent.strategy import (
    _downgrade_prediction,
    _pick_coverage_probability,
    build_ticket_plan,
    ticket_cost_yuan,
)


class StrategyTests(unittest.TestCase):
    def test_build_ticket_plan_has_14_predictions(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)

        self.assertEqual(len(plan.predictions), 14)
        self.assertEqual(len(plan.choose9_keep), 9)
        self.assertEqual(len(plan.choose9_drop), 5)
        self.assertTrue(set(plan.choose9_keep).isdisjoint(plan.choose9_drop))
        self.assertLessEqual(ticket_cost_yuan(plan.predictions), 2000)

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

    def test_report_persists_purchase_deadline_for_history(self) -> None:
        issue = replace(
            load_issue("data/sample_issue.json"),
            metadata={
                "purchase_deadline": "2026-07-25 20:30:00",
                "purchase_deadline_source": "中国体彩网官方",
                "sale_begin_time": "2026-07-22 20:00:00",
            },
        )

        report = render_markdown(build_ticket_plan(issue))

        self.assertIn("- 购彩截止时间：2026-07-25 20:30:00", report)
        self.assertIn("- 截止时间来源：中国体彩网官方", report)
        self.assertIn("- 开售时间：2026-07-22 20:00:00", report)

    def test_build_ticket_plan_respects_custom_budget(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue, max_ticket_cost_yuan=128)

        self.assertLessEqual(ticket_cost_yuan(plan.predictions), 128)

    def test_choose9_keeps_highest_recommended_outcome_coverage(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)

        expected_keep = {
            prediction.match.seq
            for prediction in sorted(
                plan.predictions,
                key=lambda prediction: (
                    _pick_coverage_probability(prediction),
                    prediction.confidence,
                    -prediction.match.seq,
                ),
                reverse=True,
            )[:9]
        }

        self.assertEqual(set(plan.choose9_keep), expected_keep)

    def test_budget_downgrade_protects_near_tied_draw_without_real_odds(self) -> None:
        prediction = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[0]
        match = replace(
            prediction.match,
            sources={**prediction.match.sources, "odds": "default_placeholder"},
        )
        uncertain = replace(
            prediction,
            match=match,
            probabilities={"3": 0.36, "1": 0.31, "0": 0.33},
            picks=("3", "1", "0"),
        )

        adjusted = _downgrade_prediction(uncertain)

        self.assertEqual(adjusted.picks, ("3", "1"))


if __name__ == "__main__":
    unittest.main()
