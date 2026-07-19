import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent.loader import load_issue
from football_lottery_agent.review import (
    MatchResult,
    build_review,
    fetch_sporttery_results,
    fetch_results_with_fallbacks,
    load_results,
    parse_outcome_results_html,
    parse_sina_results_html,
    parse_sporttery_result_row,
    render_review_markdown,
)
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

    def test_load_results_accepts_outcome_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            path.write_text("seq,outcome\n1,3\n2,平\n3,负\n", encoding="utf-8")

            results = load_results(path)

        self.assertFalse(results[1].score_exact)
        self.assertEqual(results[1].outcome, "3")
        self.assertEqual(results[2].outcome, "1")
        self.assertEqual(results[3].outcome, "0")

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

    def test_parse_outcome_results_html_extracts_issue_section(self) -> None:
        html = """
        <div>26086期 33333333333333</div>
        <div>第26087期 彩果 31031031031031</div>
        <div>26088期 00000000000000</div>
        """
        results = parse_outcome_results_html(html, "26087")

        self.assertEqual(len(results), 14)
        self.assertFalse(results[1].score_exact)
        self.assertEqual(results[1].outcome, "3")
        self.assertEqual(results[2].outcome, "1")
        self.assertEqual(results[3].outcome, "0")

    def test_fetch_results_with_fallbacks_uses_official_sporttery_source(self) -> None:
        official = {seq: MatchResult(seq, 1, 0, score_exact=False) for seq in range(1, 15)}

        with patch("football_lottery_agent.review.fetch_sporttery_results", return_value=official):
            fetched = fetch_results_with_fallbacks("26087")

        self.assertEqual(fetched.source, "中国体彩网官方开奖")
        self.assertFalse(fetched.results[1].score_exact)

    def test_fetch_results_with_fallbacks_reports_missing_official_issue(self) -> None:
        with patch("football_lottery_agent.review.fetch_sporttery_results", return_value={}):
            with self.assertRaisesRegex(ValueError, "中国体彩网官方暂未返回 26088"):
                fetch_results_with_fallbacks("26088")

    def test_fetch_sporttery_results_accepts_utf8_bom(self) -> None:
        raw = (
            '\ufeff{"errorCode":"0","value":{"list":[{"lotteryDrawNum":"26087",'
            '"lotteryDrawResult":"3","matchList":[{"matchNum":1,"result":"3","czScore":"2:1"}]}]}}'
        )
        with patch("football_lottery_agent.review._fetch_text", return_value=raw):
            results = fetch_sporttery_results("26087")

        self.assertEqual(results[1].score_text, "2-1")
        self.assertEqual(results[1].outcome, "3")

    def test_parse_sporttery_result_row_uses_match_numbers_and_official_outcomes(self) -> None:
        row = {
            "lotteryDrawNum": "26087",
            "lotteryDrawResult": "3 1 0",
            "matchList": [
                {"matchNum": 1, "masterTeamName": "荷  兰", "guestTeamName": "瑞  典", "result": "3", "czScore": "2:1"},
                {"matchNum": 2, "masterTeamName": "德  国", "guestTeamName": "科特迪", "result": "1", "czScore": "0:0"},
                {"matchNum": 3, "masterTeamName": "突尼斯", "guestTeamName": "日  本", "result": "0", "czScore": "0:2"},
            ],
        }

        results = parse_sporttery_result_row(row)

        self.assertEqual(results[1].score_text, "2-1")
        self.assertEqual(results[1].outcome, "3")
        self.assertEqual(results[2].outcome, "1")
        self.assertEqual(results[3].outcome, "0")
        self.assertTrue(results[1].score_exact)

    def test_parse_sporttery_result_row_falls_back_when_score_conflicts_with_outcome(self) -> None:
        row = {
            "lotteryDrawNum": "26087",
            "matchList": [
                {"matchNum": 1, "result": "3", "czScore": "0:1"},
            ],
        }

        results = parse_sporttery_result_row(row)

        self.assertEqual(results[1].score_text, "主胜（仅彩果）")
        self.assertFalse(results[1].score_exact)

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

    def test_build_review_skips_score_metrics_for_outcome_only_results(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: MatchResult(
                seq=prediction.match.seq,
                home_goals=1,
                away_goals=0,
                score_exact=False,
            )
            for prediction in plan.predictions
        }

        review = build_review(plan, results)

        self.assertEqual(review.score_total, 0)
        self.assertEqual(review.top_score_hits, 0)
        self.assertEqual(review.score_top3_hits, 0)
        self.assertIn("比分 Top1 命中：0/0（N/A）", render_review_markdown(review))

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

    def test_build_review_labels_a_draw_omission(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        target = next(prediction for prediction in plan.predictions if "1" not in prediction.picks)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }
        results[target.match.seq] = MatchResult(seq=target.match.seq, home_goals=0, away_goals=0)

        review = build_review(plan, results)
        row = next(item for item in review.rows if item.prediction.match.seq == target.match.seq)

        self.assertFalse(row.outcome_hit)
        self.assertIn("平局漏判", row.diagnostic_tags)
        self.assertGreater(review.diagnostic_counts["平局漏判"], 0)

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
        self.assertIn("错因记录", markdown)
        self.assertIn("| 序号 | 对阵 | 最终比分 | 彩果 |", markdown)


def _result_for_prediction(prediction):
    pick = prediction.picks[0]
    scoreline = next(
        (
            item
            for item in prediction.scorelines
            if _outcome_for_score(item.home_goals, item.away_goals) == pick
        ),
        None,
    )
    if scoreline is None:
        home_goals, away_goals = {"3": (1, 0), "1": (0, 0), "0": (0, 1)}[pick]
    else:
        home_goals, away_goals = scoreline.home_goals, scoreline.away_goals
    return MatchResult(
        seq=prediction.match.seq,
        home_goals=home_goals,
        away_goals=away_goals,
    )


def _outcome_for_score(home_goals, away_goals):
    if home_goals > away_goals:
        return "3"
    if home_goals == away_goals:
        return "1"
    return "0"


if __name__ == "__main__":
    unittest.main()
