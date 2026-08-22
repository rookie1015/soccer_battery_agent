import unittest
from dataclasses import replace
from itertools import product
from math import prod

from football_lottery_agent.loader import load_issue
from football_lottery_agent.dixon_coles import DixonColesForecast
from football_lottery_agent.predictor import _favorite_draw_guard, _has_informative_signals, _select_picks
from football_lottery_agent.report import render_markdown
from football_lottery_agent.strategy import (
    _apply_tactical_draw_strategy,
    _build_budget_portfolio,
    _downgrade_prediction,
    _fit_predictions_to_budget,
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
        self.assertTrue(all(prediction.reasons[0].startswith("选择依据：") for prediction in plan.predictions))
        self.assertFalse(any(prediction.tactical_draw for prediction in plan.predictions))
        self.assertLessEqual(plan.total_cost_yuan, plan.max_ticket_cost_yuan)

    def test_budget_portfolio_keeps_main_ticket_and_adds_separate_draw_single(self) -> None:
        base = build_ticket_plan(load_issue("data/sample_issue.json"), max_ticket_cost_yuan=2).predictions[:2]
        candidates = (
            replace(
                base[0],
                match=replace(
                    base[0].match,
                    sources={
                        **base[0].match.sources,
                        "odds_market": {"asian_current_line": 0.0},
                    },
                ),
                probabilities={"3": 0.36, "1": 0.29, "0": 0.35},
                picks=("3", "1", "0"),
                original_picks=("3", "1", "0"),
                selection_scores={},
                market_probabilities={"3": 0.35, "1": 0.30, "0": 0.35},
                dixon_coles_probabilities={"3": 0.36, "1": 0.30, "0": 0.34},
                dixon_coles_quality_score=0.60,
            ),
            replace(
                base[1],
                match=replace(
                    base[1].match,
                    sources={
                        **base[1].match.sources,
                        "odds_market": {"asian_current_line": 0.0},
                    },
                ),
                probabilities={"3": 0.37, "1": 0.28, "0": 0.35},
                picks=("3", "1", "0"),
                original_picks=("3", "1", "0"),
                selection_scores={},
                market_probabilities={"3": 0.37, "1": 0.28, "0": 0.35},
                dixon_coles_probabilities={"3": 0.37, "1": 0.29, "0": 0.34},
                dixon_coles_quality_score=0.60,
            ),
        )

        main, main_budget, hedge = _build_budget_portfolio(candidates, max_ticket_cost_yuan=10)

        self.assertEqual(main_budget, 8)
        self.assertIsNotNone(hedge)
        assert hedge is not None
        self.assertEqual(hedge.candidate_seq, candidates[0].match.seq)
        self.assertNotIn("1", main[0].picks)
        self.assertEqual(hedge.predictions[0].picks, ("1",))
        self.assertEqual(hedge.allocated_budget_yuan, 2)
        self.assertLessEqual(ticket_cost_yuan(main) + hedge.cost_yuan, 10)

    def test_three_way_pick_explains_why_no_outcome_is_excluded(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        prediction = next(item for item in plan.predictions if item.picks == ("3", "1", "0"))

        reason = prediction.reasons[0]

        self.assertIn("3/1/0 全包", reason)
        self.assertIn("主胜(3)", reason)
        self.assertIn("平局(1)", reason)
        self.assertIn("客胜(0)", reason)
        self.assertIn("没有足够把握排除任何一项", reason)

    def test_predictions_include_scorelines(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        prediction = plan.predictions[0]

        self.assertEqual(len(prediction.scorelines), 3)
        self.assertGreater(prediction.scorelines[0].probability, 0)
        self.assertGreaterEqual(prediction.scorelines[0].probability, prediction.scorelines[1].probability)

    def test_report_hides_scoreline_and_risk_but_keeps_confidence(self) -> None:
        issue = load_issue("data/sample_issue.json")
        plan = build_ticket_plan(issue)
        report = render_markdown(plan)

        self.assertNotIn("比分倾向", report)
        self.assertNotIn("| 风险 |", report)
        self.assertIn("置信度", report)

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
        self.assertIn("双选 3/1", adjusted.reasons[0])
        self.assertTrue(any("移除客胜(0)" in reason for reason in adjusted.reasons))

    def test_simple_analysis_keeps_existing_near_tie_behavior(self) -> None:
        ranked = [("3", 0.46), ("0", 0.275), ("1", 0.265)]

        self.assertEqual(_select_picks(ranked), ("3", "1", "0"))

    def test_default_policy_no_longer_calls_58_percent_a_single(self) -> None:
        ranked = [("3", 0.58), ("1", 0.23), ("0", 0.19)]

        self.assertEqual(_select_picks(ranked), ("3", "1"))

    def test_strong_favourite_keeps_draw_when_goal_model_warns(self) -> None:
        forecast = DixonColesForecast(
            home_xg=1.7,
            away_xg=0.8,
            probabilities={"3": 0.59, "1": 0.25, "0": 0.16},
            data_quality="strength",
            data_quality_score=0.80,
        )

        self.assertTrue(
            _favorite_draw_guard(
                {"3": 0.68, "1": 0.19, "0": 0.13},
                ("3",),
                forecast,
            )
        )
        self.assertFalse(
            _favorite_draw_guard(
                {"3": 0.73, "1": 0.16, "0": 0.11},
                ("3",),
                forecast,
            )
        )

    def test_full_analysis_without_evidence_does_not_apply_legacy_draw_bonus(self) -> None:
        prediction = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[0]
        match = replace(
            prediction.match,
            sources={**prediction.match.sources, "collection_audit": {"mode": "full"}},
        )
        uncertain = replace(
            prediction,
            match=match,
            probabilities={"3": 0.36, "1": 0.31, "0": 0.33},
            picks=("3", "1", "0"),
            selection_scores={},
        )

        adjusted = _downgrade_prediction(uncertain)

        self.assertEqual(adjusted.picks, ("3", "0"))

    def test_full_analysis_can_choose_draw_from_supporting_evidence(self) -> None:
        ranked = [("3", 0.46), ("0", 0.275), ("1", 0.265)]
        evidence_scores = {"3": 0.46, "1": 0.30, "0": 0.25}

        self.assertEqual(
            _select_picks(ranked, selection_scores=evidence_scores),
            ("3", "1"),
        )

    def test_full_analysis_can_choose_non_draw_from_supporting_evidence(self) -> None:
        ranked = [("3", 0.46), ("1", 0.275), ("0", 0.265)]
        evidence_scores = {"3": 0.46, "1": 0.25, "0": 0.31}

        self.assertEqual(
            _select_picks(ranked, selection_scores=evidence_scores),
            ("3", "0"),
        )

    def test_full_analysis_keeps_three_choices_when_evidence_is_inconclusive(self) -> None:
        ranked = [("3", 0.46), ("0", 0.275), ("1", 0.265)]
        evidence_scores = {"3": 0.46, "1": 0.272, "0": 0.275}

        self.assertEqual(
            _select_picks(ranked, selection_scores=evidence_scores),
            ("3", "1", "0"),
        )

    def test_full_analysis_budget_downgrade_uses_evidence_scores(self) -> None:
        prediction = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[0]
        uncertain = replace(
            prediction,
            probabilities={"3": 0.46, "1": 0.26, "0": 0.28},
            picks=("3", "1", "0"),
            selection_scores={"3": 0.46, "1": 0.30, "0": 0.25},
        )

        adjusted = _downgrade_prediction(uncertain)

        self.assertEqual(adjusted.picks, ("3", "1"))

    def test_full_evidence_gate_does_not_treat_default_numbers_as_real_evidence(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        audit = {
            "mode": "full",
            "injuries": {"status": "confirmed_empty", "count": 0},
            "intelligence": {"status": "confirmed_empty", "count": 0},
            "history": {"status": "confirmed_empty", "count": 0},
            "strength": {"status": "unmatched"},
            "xg": {"status": "missing"},
        }
        no_evidence = replace(match, sources={**match.sources, "collection_audit": audit})
        with_evidence = replace(
            match,
            sources={
                **match.sources,
                "collection_audit": {**audit, "intelligence": {"status": "available", "count": 2}},
            },
        )

        self.assertFalse(_has_informative_signals(no_evidence))
        self.assertTrue(_has_informative_signals(with_evidence))

    def test_budget_optimizer_finds_global_best_discrete_coverage(self) -> None:
        base = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[:3]
        probabilities = (
            {"3": 0.55, "1": 0.25, "0": 0.20},
            {"3": 0.46, "1": 0.30, "0": 0.24},
            {"3": 0.40, "1": 0.33, "0": 0.27},
        )
        predictions = tuple(
            replace(item, probabilities=values, selection_scores=values, picks=("3", "1", "0"))
            for item, values in zip(base, probabilities)
        )

        adjusted = _fit_predictions_to_budget(predictions, max_ticket_cost_yuan=16)
        actual = prod(sum(item.probabilities[pick] for pick in item.picks) for item in adjusted)
        expected = max(
            prod(sum(sorted(values.values(), reverse=True)[:count]) for values, count in zip(probabilities, counts))
            for counts in product((1, 2, 3), repeat=3)
            if prod(counts) <= 8
        )

        self.assertAlmostEqual(actual, expected, places=8)

    def test_budget_single_preserves_original_selection_and_marks_warning(self) -> None:
        prediction = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[0]
        uncertain = replace(
            prediction,
            probabilities={"3": 0.43, "1": 0.27, "0": 0.30},
            picks=("3", "1", "0"),
            original_picks=("3", "1", "0"),
            selection_scores={},
        )

        adjusted = _fit_predictions_to_budget((uncertain,), max_ticket_cost_yuan=2)[0]

        self.assertEqual(adjusted.analysis_picks, ("3", "1", "0"))
        self.assertEqual(adjusted.picks, ("3",))
        self.assertTrue(adjusted.budget_adjusted)
        self.assertTrue(adjusted.budget_forced_single)
        self.assertEqual(adjusted.risk, "高")

    def test_budget_optimizer_avoids_model_conflict_single_when_safe_choice_exists(self) -> None:
        base = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[:2]
        conflict = replace(
            base[0],
            match=replace(base[0].match, sources={}),
            probabilities={"3": 0.70, "1": 0.16, "0": 0.14},
            picks=("3", "1", "0"),
            original_picks=("3", "1", "0"),
            selection_scores={},
            dixon_coles_probabilities={"3": 0.30, "1": 0.25, "0": 0.45},
            dixon_coles_quality_score=0.80,
            budget_adjusted=False,
            budget_forced_single=False,
            budget_removed_picks=(),
        )
        safe = replace(
            base[1],
            match=replace(base[1].match, sources={}),
            probabilities={"3": 0.60, "1": 0.22, "0": 0.18},
            picks=("3", "1", "0"),
            original_picks=("3", "1", "0"),
            selection_scores={},
            dixon_coles_probabilities={"3": 0.61, "1": 0.22, "0": 0.17},
            dixon_coles_quality_score=0.80,
            budget_adjusted=False,
            budget_forced_single=False,
            budget_removed_picks=(),
        )

        adjusted = _fit_predictions_to_budget((conflict, safe), max_ticket_cost_yuan=6)

        self.assertEqual(adjusted[0].picks, ("3", "1", "0"))
        self.assertEqual(adjusted[1].picks, ("3",))
        self.assertFalse(adjusted[1].budget_forced_single)

    def test_issue_can_select_one_explicit_high_risk_tactical_draw(self) -> None:
        base = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[:2]
        candidates = tuple(
            replace(
                prediction,
                match=replace(
                    prediction.match,
                    sources={
                        **prediction.match.sources,
                        "odds": "sina_average_euro",
                        "odds_market": {
                            "market_movement": {"3": -0.005, "1": 0.010, "0": -0.005},
                            "asian_current_line": 0.0,
                        },
                    },
                ),
                probabilities={"3": 0.34, "1": 0.32 - index * 0.01, "0": 0.34 + index * 0.01},
                picks=("3", "1", "0"),
                original_picks=("3", "1", "0"),
                market_probabilities={"3": 0.36, "1": 0.29, "0": 0.35},
                dixon_coles_probabilities={"3": 0.335, "1": 0.33, "0": 0.335},
                dixon_coles_quality="strength",
                dixon_coles_quality_score=0.80,
                tactical_draw=False,
            )
            for index, prediction in enumerate(base)
        )

        adjusted = _apply_tactical_draw_strategy(candidates)
        tactical = [prediction for prediction in adjusted if prediction.tactical_draw]

        self.assertEqual(len(tactical), 1)
        self.assertEqual(tactical[0].match.seq, candidates[0].match.seq)
        self.assertEqual(tactical[0].picks, ("1",))
        self.assertEqual(tactical[0].analysis_picks, ("1",))
        self.assertEqual(tactical[0].risk, "高")
        self.assertTrue(any("不是稳胆" in reason for reason in tactical[0].reasons))

    def test_tactical_draw_rejects_low_quality_math(self) -> None:
        prediction = build_ticket_plan(load_issue("data/sample_issue.json")).predictions[0]
        candidate = replace(
            prediction,
            probabilities={"3": 0.34, "1": 0.32, "0": 0.34},
            market_probabilities={"3": 0.36, "1": 0.29, "0": 0.35},
            dixon_coles_probabilities={"3": 0.335, "1": 0.33, "0": 0.335},
            dixon_coles_quality_score=0.30,
        )

        adjusted = _apply_tactical_draw_strategy((candidate,))

        self.assertFalse(adjusted[0].tactical_draw)


if __name__ == "__main__":
    unittest.main()
