import tempfile
import unittest
from pathlib import Path

from football_lottery_agent.loader import load_issue
from football_lottery_agent.review import MatchResult, build_review, load_results, parse_sina_results_html, render_review_markdown
from football_lottery_agent.strategy import build_ticket_plan


class ReviewTests(unittest.TestCase):
    def test_load_results_accepts_score_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            path.write_text("seq,score\n1,2-1\n2,0:0\n", encoding="utf-8")

            results = load_results(path)

        self.assertEqual(results[1].score_text, "2-1")
        self.assertEqual(results[1].outcome, "3")
        self.assertEqual(results[2].score_text, "0-0")
        self.assertEqual(results[2].outcome, "1")

    def test_parse_sina_results_html_extracts_finished_scores(self) -> None:
        html = """
        <table class="sfcPubTable"><tbody>
          <tr><td>01</td><td>世界杯</td><td>06-21</td><td>荷兰</td><td>2-1</td><td>瑞典</td><td><strong>3</strong></td></tr>
          <tr><td>02</td><td>世界杯</td><td>06-21</td><td>德国</td><td>-</td><td>科特迪瓦</td><td></td></tr>
          <tr><td>03</td><td>世界杯</td><td>06-21</td><td>突尼斯</td><td>0:2</td><td>日本</td><td><strong>0</strong></td></tr>
        </tbody></table>
        """
        results = parse_sina_results_html(html)

        self.assertEqual(results[1].score_text, "2-1")
        self.assertEqual(results[1].outcome, "3")
        self.assertEqual(results[3].score_text, "0-2")
        self.assertNotIn(2, results)

    def test_build_review_counts_outcome_and_score_hits(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }

        review = build_review(plan, results)

        self.assertEqual(review.total, 14)
        self.assertEqual(review.outcome_hits, 14)
        self.assertGreaterEqual(review.score_top3_hits, 1)
        self.assertEqual(len(review.keep_rows), 9)
        self.assertEqual(len(review.drop_rows), 5)

    def test_build_review_flags_major_miss(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }
        first_single = next(prediction for prediction in plan.predictions if len(prediction.picks) == 1)
        results[first_single.match.seq] = MatchResult(
            seq=first_single.match.seq,
            home_goals=0,
            away_goals=1,
        )

        review = build_review(plan, results)

        self.assertEqual(len(review.major_misses), 1)
        self.assertEqual(review.major_misses[0].prediction.match.seq, first_single.match.seq)

    def test_render_review_markdown_contains_summary_and_rows(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }
        review = build_review(plan, results)

        markdown = render_review_markdown(review)

        self.assertIn("胜平负命中", markdown)
        self.assertIn("比分 Top3 命中", markdown)
        self.assertIn("| 序号 | 对阵 | 赛果 |", markdown)


def _result_for_prediction(prediction):
    scoreline = prediction.scorelines[0]
    return MatchResult(
        seq=prediction.match.seq,
        home_goals=scoreline.home_goals,
        away_goals=scoreline.away_goals,
    )


if __name__ == "__main__":
    unittest.main()
