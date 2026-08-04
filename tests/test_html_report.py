import unittest
from dataclasses import replace

from football_lottery_agent.html_report import render_analysis_html, render_review_html
from football_lottery_agent.loader import load_issue
from football_lottery_agent.review import MatchResult, build_review
from football_lottery_agent.strategy import build_ticket_plan


class HtmlReportTests(unittest.TestCase):
    def test_render_analysis_html_contains_dashboard_sections(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))

        html = render_analysis_html(plan)

        self.assertIn("Analysis Dashboard", html)
        self.assertIn("逐场胜平负分析", html)
        self.assertIn('id="outcome-panel"', html)
        self.assertIn("class=\"prob\"", html)
        self.assertIn("置信度", html)
        self.assertNotIn("<th>风险</th>", html)
        self.assertNotIn("单场比分预测", html)
        self.assertEqual(html.count('class="match-tab"'), 14)
        self.assertIn("得出结论的理由", html)
        self.assertIn("点击任意比赛查看结论、概率、置信度和判断依据，再点一次收起", html)
        self.assertIn(plan.predictions[0].reasons[0], html)
        self.assertIn("购彩截止时间：官方截止时间暂未获取", html)
        self.assertIn("逐场胜平负分析", html)

    def test_render_analysis_html_uses_official_purchase_deadline(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        plan = replace(
            plan,
            issue=replace(plan.issue, metadata={"purchase_deadline": "2026-07-04 23:00:00"}),
        )

        html = render_analysis_html(plan)

        self.assertIn("购彩截止时间：2026-07-04 23:00:00", html)

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
        self.assertIn("<th>最终比分</th>", html)
        self.assertIn("<th>彩果</th>", html)
        self.assertIn("<th>比分预测</th>", html)
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
