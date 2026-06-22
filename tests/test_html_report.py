import unittest

from football_lottery_agent.html_report import render_analysis_html, render_review_html
from football_lottery_agent.loader import load_issue
from football_lottery_agent.review import MatchResult, build_review
from football_lottery_agent.strategy import build_ticket_plan


class HtmlReportTests(unittest.TestCase):
    def test_render_analysis_html_contains_dashboard_sections(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))

        html = render_analysis_html(plan)

        self.assertIn("Analysis Dashboard", html)
        self.assertIn("胜平负预测", html)
        self.assertIn("单场比分预测", html)
        self.assertIn('id="outcome-panel"', html)
        self.assertIn('id="score-panel"', html)
        self.assertIn("首选比分", html)
        self.assertIn("class=\"prob\"", html)
        self.assertIn("class=\"primary-score\"", html)
        self.assertIn("class=\"panel prediction-fold\"", html)
        self.assertIn("展开本期 14 场胜平负预测", html)

    def test_render_review_html_contains_metrics_and_rows(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        results = {
            prediction.match.seq: MatchResult(
                seq=prediction.match.seq,
                home_goals=prediction.scorelines[0].home_goals,
                away_goals=prediction.scorelines[0].away_goals,
            )
            for prediction in plan.predictions
        }
        review = build_review(plan, results)

        html = render_review_html(review)

        self.assertIn("Review Dashboard", html)
        self.assertIn("胜平负命中", html)
        self.assertIn("比分 Top3", html)
        self.assertIn("class=\"meter\"", html)

    def test_render_review_html_highlights_major_misses(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        results = {
            prediction.match.seq: MatchResult(
                seq=prediction.match.seq,
                home_goals=prediction.scorelines[0].home_goals,
                away_goals=prediction.scorelines[0].away_goals,
            )
            for prediction in plan.predictions
        }
        first_single = next(prediction for prediction in plan.predictions if len(prediction.picks) == 1)
        results[first_single.match.seq] = MatchResult(seq=first_single.match.seq, home_goals=0, away_goals=1)
        review = build_review(plan, results)

        html = render_review_html(review)

        self.assertIn("重大意外", html)
        self.assertIn("upset-card", html)


if __name__ == "__main__":
    unittest.main()
