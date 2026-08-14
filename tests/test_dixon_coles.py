import unittest
from dataclasses import replace

from football_lottery_agent.dixon_coles import forecast
from football_lottery_agent.loader import load_issue
from football_lottery_agent.models import Match, Odds
from football_lottery_agent.predictor import (
    _apply_venue_form_adjustment,
    _blend_weights,
    _select_picks,
    _signal_scores,
    predict_match,
)


class DixonColesTests(unittest.TestCase):
    def test_venue_form_uses_shrunk_residual_instead_of_raw_home_away_comparison(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        probabilities = {"3": 0.20, "1": 0.20, "0": 0.60}
        venue_match = replace(
            match,
            sources={
                "strength_model": {
                    "home_overall_win_rate": 0.45,
                    "home_venue_win_rate": 0.50,
                    "home_venue_matches": 4,
                    "away_overall_win_rate": 0.70,
                    "away_venue_win_rate": 0.25,
                    "away_venue_matches": 4,
                }
            },
        )

        adjusted, details = _apply_venue_form_adjustment(venue_match, probabilities)

        self.assertGreater(adjusted["3"], probabilities["3"])
        self.assertLess(adjusted["0"], probabilities["0"])
        self.assertLessEqual(abs(details["shift"]), 0.04)

    def test_venue_form_ignores_one_match_samples(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        probabilities = {"3": 0.20, "1": 0.20, "0": 0.60}
        tiny_sample = replace(
            match,
            sources={
                "strength_model": {
                    "home_overall_win_rate": 0.45,
                    "home_venue_win_rate": 1.0,
                    "home_venue_matches": 1,
                    "away_overall_win_rate": 0.70,
                    "away_venue_win_rate": 0.0,
                    "away_venue_matches": 1,
                }
            },
        )

        adjusted, details = _apply_venue_form_adjustment(tiny_sample, probabilities)

        self.assertEqual(adjusted, probabilities)
        self.assertEqual(details, {})

    def test_large_first_leg_lead_prevents_benfica_away_single(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        benfica_match = replace(
            match,
            league="欧罗巴",
            home="哈茨",
            away="本菲卡",
            odds=Odds(home=6.80, draw=4.70, away=1.36),
            sources={
                "strength_model": {
                    "home_overall_win_rate": 0.40,
                    "home_venue_win_rate": 0.60,
                    "home_venue_matches": 5,
                    "away_overall_win_rate": 0.75,
                    "away_venue_win_rate": 0.25,
                    "away_venue_matches": 4,
                },
                "knockout_context": {
                    "is_second_leg": True,
                    "first_leg_home_goals": 1,
                    "first_leg_away_goals": 6,
                    "aggregate_margin_home": -5,
                },
            },
        )
        ordinary_match = replace(benfica_match, sources={"strength_model": benfica_match.sources["strength_model"]})

        forced_single_policy = {"single_top": 0.40, "single_spread": 0.10}
        prediction = predict_match(benfica_match, selection_policy=forced_single_policy)
        ordinary = predict_match(ordinary_match, selection_policy=forced_single_policy)

        self.assertLess(prediction.probabilities["0"], ordinary.probabilities["0"])
        self.assertTrue(prediction.draw_guard)
        self.assertIn("0", prediction.picks)
        self.assertIn("1", prediction.picks)
        self.assertTrue(any("次回合单选保护" in reason for reason in prediction.reasons))
        self.assertTrue(any("同场地近期表现" in reason for reason in prediction.reasons))

    def test_forecast_returns_normalized_outcome_probabilities(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]

        result = forecast(match)

        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0, places=6)
        self.assertGreater(result.home_xg, 0)
        self.assertGreater(result.away_xg, 0)
        self.assertEqual(result.data_quality, "signal_fallback")

    def test_strength_xg_is_used_when_available(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        strength_match = replace(
            match,
            sources={
                "strength_model": {
                    "home_xg_for": 2.0,
                    "home_xg_against": 0.8,
                    "away_xg_for": 0.8,
                    "away_xg_against": 1.8,
                }
            },
        )

        result = forecast(strength_match)

        self.assertEqual(result.data_quality, "strength")
        self.assertGreater(result.probabilities["3"], result.probabilities["0"])

    def test_goals_only_history_uses_hierarchical_fallback(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        goals_match = replace(
            match,
            sources={
                "strength_model": {
                    "home_goals_for": 2.4,
                    "home_goals_against": 0.7,
                    "away_goals_for": 0.8,
                    "away_goals_against": 1.9,
                    "home_matches_used": 10,
                    "away_matches_used": 10,
                }
            },
        )

        result = forecast(goals_match)
        weights = _blend_weights(goals_match, result, None)

        self.assertEqual(result.data_quality, "hierarchical")
        self.assertGreater(result.data_quality_score, 0.5)
        self.assertGreater(result.probabilities["3"], result.probabilities["0"])
        self.assertAlmostEqual(weights[2], 0.18)

    def test_short_xg_sample_is_shrunk_toward_league_prior(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        short_sample = replace(
            match,
            sources={
                "strength_model": {
                    "home_xg_for": 3.0,
                    "home_xg_against": 0.4,
                    "away_xg_for": 0.5,
                    "away_xg_against": 2.8,
                    "home_xg_matches": 1,
                    "away_xg_matches": 1,
                }
            },
        )

        result = forecast(short_sample)

        self.assertEqual(result.data_quality, "partial_strength")
        self.assertLess(result.home_xg, 2.0)
        self.assertGreater(result.away_xg, 0.6)

    def test_recent_draw_rates_adjust_low_score_correlation(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        base = {
            "home_xg_for": 1.0,
            "home_xg_against": 1.0,
            "away_xg_for": 1.0,
            "away_xg_against": 1.0,
            "home_xg_matches": 8,
            "away_xg_matches": 8,
        }
        high_draw = forecast(
            replace(
                match,
                sources={"strength_model": {**base, "home_draw_rate": 0.45, "away_draw_rate": 0.45}},
            )
        )
        low_draw = forecast(
            replace(
                match,
                sources={"strength_model": {**base, "home_draw_rate": 0.10, "away_draw_rate": 0.10}},
            )
        )

        self.assertGreater(high_draw.probabilities["1"], low_draw.probabilities["1"])

    def test_predictor_includes_math_model_reason(self) -> None:
        prediction = predict_match(load_issue("data/sample_issue.json").matches[0])

        self.assertTrue(any("Dixon-Coles" in reason for reason in prediction.reasons))

    def test_predictor_explains_network_sources_missing_from_full_analysis(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        fallback_match = replace(
            match,
            sources={
                **match.sources,
                "analysis_network_fallback": {
                    "scope": "match",
                    "unavailable_sources": ["伤停信息", "历史交锋", "赔率变化"],
                },
            },
        )

        prediction = predict_match(fallback_match)
        reason = next(item for item in prediction.reasons if item.startswith("完整分析资料审计（网络降级）"))

        self.assertIn("完整分析未执行", reason)
        self.assertIn("本场因网络未获得的信息来源：伤停信息、历史交锋、赔率变化", reason)
        self.assertIn("这些资料未参与判断", reason)

    def test_collection_audit_explains_identity_xg_and_totals_gaps(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        audit_match = replace(
            match,
            sources={
                **match.sources,
                "collection_audit": {
                    "mode": "full",
                    "strength": {
                        "status": "unmatched",
                        "reason": "ambiguous_context_missing_aliases",
                        "candidate_count": 24,
                        "sofascore_status": "blocked",
                    },
                    "xg": {"status": "missing", "reason": "team_identity_unmatched"},
                    "totals": {"status": "not_available_from_provider"},
                },
            },
        )

        reason = next(item for item in predict_match(audit_match).reasons if item.startswith("完整分析资料审计："))

        self.assertIn("同联赛同时间存在24场候选", reason)
        self.assertIn("SofaScore访问受限", reason)
        self.assertIn("无法取得球队ID和xG样本", reason)
        self.assertIn("当前赔率源没有提供大小球盘口", reason)

    def test_squad_strength_and_absence_adjust_the_xg_prior(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        base_sources = {
            "strength_model": {
                "home_xg_for": 1.5,
                "home_xg_against": 1.1,
                "away_xg_for": 1.3,
                "away_xg_against": 1.2,
                "home_squad_paper_rating": 30.0,
                "away_squad_paper_rating": 20.0,
            }
        }
        strong_home = forecast(replace(match, sources=base_sources))
        weakened_home = forecast(
            replace(match, sources={"strength_model": {**base_sources["strength_model"], "home_squad_availability_penalty": 0.35}})
        )

        self.assertGreater(strong_home.home_xg, strong_home.away_xg)
        self.assertLess(weakened_home.home_xg, strong_home.home_xg)

    def test_low_scoring_balanced_teams_raise_draw_signal(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        low_scoring = replace(
            match,
            sources={
                "strength_model": {
                    "home_xg_for": 0.7,
                    "home_xg_against": 0.7,
                    "away_xg_for": 0.7,
                    "away_xg_against": 0.7,
                    "home_draw_rate": 0.40,
                    "away_draw_rate": 0.40,
                }
            },
        )
        high_scoring = replace(
            match,
            sources={
                "strength_model": {
                    "home_xg_for": 1.8,
                    "home_xg_against": 1.8,
                    "away_xg_for": 1.8,
                    "away_xg_against": 1.8,
                    "home_draw_rate": 0.15,
                    "away_draw_rate": 0.15,
                }
            },
        )

        low_probabilities = _signal_scores(low_scoring)
        high_probabilities = _signal_scores(high_scoring)

        self.assertGreater(low_probabilities["1"], low_probabilities["3"])
        self.assertGreater(low_probabilities["1"], low_probabilities["0"])
        self.assertGreater(low_probabilities["1"], high_probabilities["1"])

    def test_close_second_and_third_probabilities_keep_triple_cover(self) -> None:
        picks = _select_picks([("0", 0.45), ("3", 0.28), ("1", 0.27)])

        self.assertEqual(picks, ("3", "1", "0"))

    def test_learned_weights_apply_to_signal_fallback(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        math_forecast = forecast(match)

        weights = _blend_weights(
            match,
            math_forecast,
            {"odds": 0.20, "signals": 0.70, "dixon_coles": 0.10},
        )

        for actual, expected in zip(weights, (0.20, 0.70, 0.10)):
            self.assertAlmostEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
