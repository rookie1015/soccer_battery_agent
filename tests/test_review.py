import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent.loader import load_issue
from football_lottery_agent.review import (
    MatchResult,
    REVIEW_PLAY_CHOOSE9,
    _diagnostic_tags,
    build_review,
    fetch_sporttery_prize,
    fetch_sporttery_results,
    fetch_results_with_fallbacks,
    load_results,
    parse_outcome_results_html,
    parse_sina_results_html,
    parse_sporttery_result_row,
    render_review_markdown,
)
from football_lottery_agent.strategy import _build_line_portfolio, _fit_predictions_to_budget, build_ticket_plan


class ReviewTests(unittest.TestCase):
    def test_choose9_review_uses_only_independent_nine_match_ticket(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"), max_ticket_cost_yuan=500)
        assert plan.choose9_plan is not None
        choose9_by_seq = {
            prediction.match.seq: prediction
            for prediction in plan.choose9_plan.predictions
        }
        results = {}
        for prediction in plan.predictions:
            chosen = choose9_by_seq.get(prediction.match.seq, prediction)
            outcome = chosen.picks[0]
            score = (1, 0) if outcome == "3" else (0, 0) if outcome == "1" else (0, 1)
            results[prediction.match.seq] = MatchResult(prediction.match.seq, *score)

        review = build_review(plan, results, play_type=REVIEW_PLAY_CHOOSE9)
        markdown = render_review_markdown(review)

        self.assertEqual(review.total, 9)
        self.assertEqual(review.outcome_hits, 9)
        self.assertTrue(all(row.bucket == "任九选择" for row in review.rows))
        self.assertIn("复盘玩法：任九", markdown)
        self.assertIn("任九胜平负命中：9/9", markdown)

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

    def test_load_results_accepts_unplayed_star(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            path.write_text("seq,outcome\n1,*\n2,＊\n", encoding="utf-8")

            results = load_results(path)

        self.assertTrue(results[1].unplayed)
        self.assertEqual(results[1].outcome, "*")
        self.assertEqual(results[1].outcome_label, "未进行（3/1/0均正确）")
        self.assertTrue(results[2].unplayed)

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

    def test_fetch_sporttery_prize_reads_both_games(self) -> None:
        raw = '''{"errorCode":"0","value":{"list":[{
          "lotteryDrawNum":"26087","lotteryDrawTime":"2026-07-08",
          "prizeLevelList":[
            {"prizeLevel":"一等奖","stakeAmountFormat":"123456"},
            {"prizeLevel":"二等奖","stakeAmount":"7,890"}],
          "prizeLevelListRj":[{"prizeLevel":"任选9场","stakeAmountFormat":"4567"}]
        }]}}'''
        with patch("football_lottery_agent.review._fetch_text", return_value=raw):
            prize = fetch_sporttery_prize("26087")

        self.assertEqual(prize.draw_date, "2026-07-08")
        self.assertEqual(prize.sfc14_first_yuan, 123456)
        self.assertEqual(prize.sfc14_second_yuan, 7890)
        self.assertEqual(prize.choose9_yuan, 4567)
        self.assertTrue(prize.published)

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

    def test_parse_sporttery_result_row_recognizes_unplayed_star(self) -> None:
        row = {
            "lotteryDrawNum": "26087",
            "lotteryDrawResult": "3 1 *",
            "matchList": [
                {"matchNum": 1, "result": "3", "czScore": "2:1"},
                {"matchNum": 2, "result": "1", "czScore": "0:0"},
                {"matchNum": 3, "result": "", "czScore": "*"},
            ],
        }

        results = parse_sporttery_result_row(row)

        self.assertTrue(results[3].unplayed)
        self.assertEqual(results[3].score_text, "*（比赛未进行）")

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

    def test_build_review_counts_unplayed_star_as_hit_for_any_pick(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }
        target = plan.predictions[0]
        results[target.match.seq] = MatchResult(
            seq=target.match.seq,
            home_goals=0,
            away_goals=0,
            unplayed=True,
        )

        review = build_review(plan, results)
        row = next(item for item in review.rows if item.prediction.match.seq == target.match.seq)

        self.assertTrue(row.outcome_hit)
        self.assertTrue(row.analysis_outcome_hit)
        self.assertFalse(row.top_score_hit)
        self.assertFalse(row.score_top3_hit)
        self.assertEqual(row.diagnostic_tags, ())
        self.assertIn("未进行（3/1/0均正确）", render_review_markdown(review))

    def test_build_review_flags_major_miss(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        results = {
            prediction.match.seq: _result_for_prediction(prediction)
            for prediction in plan.predictions
        }
        first = plan.predictions[0]
        first_single = replace(first, picks=(first.picks[0],), original_picks=(first.picks[0],))
        plan = replace(plan, predictions=(first_single, *plan.predictions[1:]))
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
        first = plan.predictions[0]
        target = replace(first, picks=tuple(pick for pick in first.picks if pick != "1"))
        plan = replace(plan, predictions=(target, *plan.predictions[1:]))
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

    def test_review_distinguishes_budget_caused_miss(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        prediction = replace(
            plan.predictions[0],
            probabilities={"3": 0.43, "1": 0.27, "0": 0.30},
            picks=("3", "1", "0"),
            original_picks=("3", "1", "0"),
            selection_scores={},
        )
        forced = _fit_predictions_to_budget((prediction,), max_ticket_cost_yuan=2)[0]
        result = MatchResult(seq=forced.match.seq, home_goals=0, away_goals=0)

        tags = _diagnostic_tags(forced, result)
        review = build_review(
            replace(plan, predictions=(forced,), choose9_keep=(forced.match.seq,), choose9_drop=()),
            {forced.match.seq: result},
        )

        self.assertIn("预算压缩导致漏判", tags)
        self.assertIn("平局漏判", tags)
        self.assertEqual(review.budget_draw_caused_misses, 1)
        self.assertIn("其中预算删平导致漏判：1 场", render_review_markdown(review))

    def test_review_records_line_portfolio_hit_and_draw_combination_coverage(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        portfolio = _build_line_portfolio(plan.predictions, max_ticket_cost_yuan=2000)
        plan = replace(plan, line_portfolio=portfolio, main_cost_yuan=portfolio.cost_yuan)
        self.assertIsNotNone(plan.line_portfolio)
        assert plan.line_portfolio is not None
        result_by_outcome = {
            "3": (1, 0),
            "1": (0, 0),
            "0": (0, 1),
        }
        results = {}
        winning_line = plan.line_portfolio.lines[0]
        for prediction, outcome in zip(plan.predictions, winning_line.outcomes):
            home_goals, away_goals = result_by_outcome[outcome]
            results[prediction.match.seq] = MatchResult(
                seq=prediction.match.seq,
                home_goals=home_goals,
                away_goals=away_goals,
            )

        review = build_review(plan, results)

        self.assertTrue(review.line_portfolio_hit)
        self.assertEqual(review.line_portfolio_best_hits, 14)
        self.assertGreater(review.actual_draw_combination_lines, 0)
        self.assertIn("独立线路：最佳一注命中 14/14", render_review_markdown(review))

    def test_review_scores_choose9_with_its_independent_ticket_picks(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"), max_ticket_cost_yuan=2000)
        assert plan.choose9_plan is not None
        main_by_seq = {prediction.match.seq: prediction for prediction in plan.predictions}
        expanded = next(
            prediction
            for prediction in plan.choose9_plan.predictions
            if any(pick not in main_by_seq[prediction.match.seq].picks for pick in prediction.picks)
        )
        extra_outcome = next(
            pick for pick in expanded.picks if pick not in main_by_seq[expanded.match.seq].picks
        )
        scores = {"3": (1, 0), "1": (0, 0), "0": (0, 1)}
        results = {
            prediction.match.seq: MatchResult(
                seq=prediction.match.seq,
                home_goals=scores[prediction.picks[0]][0],
                away_goals=scores[prediction.picks[0]][1],
            )
            for prediction in plan.predictions
        }
        results[expanded.match.seq] = MatchResult(
            seq=expanded.match.seq,
            home_goals=scores[extra_outcome][0],
            away_goals=scores[extra_outcome][1],
        )

        review = build_review(plan, results)
        row = next(item for item in review.rows if item.result.seq == expanded.match.seq)

        self.assertFalse(row.outcome_hit)
        self.assertTrue(row.choose9_outcome_hit)
        self.assertEqual(review.keep_hits, 9)


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
