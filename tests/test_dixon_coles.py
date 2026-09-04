import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from football_lottery_agent.dixon_coles import forecast
from football_lottery_agent.loader import load_issue
from football_lottery_agent.models import Match, Odds
from football_lottery_agent.predictor import (
    _blend_weights,
    _cap_market_anchor_shift,
    _effective_blend_weights,
    _full_analysis_selection_scores,
    _select_picks,
    _signal_scores,
    predict_match,
)


class DixonColesTests(unittest.TestCase):
    @staticmethod
    def _history_row(
        match_id: int,
        kickoff: datetime,
        home_id: int,
        away_id: int,
        home_xg: float,
        away_xg: float,
        *,
        league_id: int = 10,
        neutral: bool = False,
    ) -> dict[str, object]:
        return {
            "match_id": match_id,
            "kickoff": kickoff.isoformat(),
            "league_id": league_id,
            "league": f"League {league_id}",
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team": f"Team {home_id}",
            "away_team": f"Team {away_id}",
            "home_goals": round(home_xg),
            "away_goals": round(away_xg),
            "home_xg": home_xg,
            "away_xg": away_xg,
            "neutral_venue": neutral,
        }

    def test_recent_match_history_uses_fitted_dixon_coles_model(self) -> None:
        kickoff = datetime(2026, 9, 10, tzinfo=timezone.utc)
        home_history = [
            self._history_row(index, kickoff - timedelta(days=index * 7), 1, 100 + index, 2.2, 0.7)
            for index in range(1, 9)
        ]
        away_history = [
            self._history_row(100 + index, kickoff - timedelta(days=index * 7 + 2), 200 + index, 2, 1.6, 0.8)
            for index in range(1, 9)
        ]
        match = replace(
            load_issue("data/sample_issue.json").matches[0],
            kickoff=kickoff,
            sources={
                "strength_model": {
                    "home_team_id": 1,
                    "away_team_id": 2,
                    "candidate_league_id": 10,
                    "home_recent_matches": home_history,
                    "away_recent_matches": away_history,
                }
            },
        )

        result = forecast(match)

        self.assertEqual(result.model_version, "fitted-dixon-coles-v1")
        self.assertEqual(result.data_quality, "fitted")
        self.assertEqual(result.fit_sample_count, 16)
        self.assertGreater(result.home_xg, result.away_xg)
        self.assertGreater(result.probabilities["3"], result.probabilities["0"])

    def test_league_scoring_environment_is_fitted_separately(self) -> None:
        kickoff = datetime(2026, 9, 10, tzinfo=timezone.utc)
        history = []
        for index in range(1, 9):
            history.append(self._history_row(index, kickoff - timedelta(days=index * 5), 1, 2, 2.4, 1.8, league_id=10))
            history.append(self._history_row(100 + index, kickoff - timedelta(days=index * 5 + 1), 1, 2, 0.9, 0.6, league_id=20))
        base = replace(load_issue("data/sample_issue.json").matches[0], kickoff=kickoff)

        high = forecast(
            replace(
                base,
                sources={"strength_model": {
                    "home_team_id": 1,
                    "away_team_id": 2,
                    "candidate_league_id": 10,
                    "home_recent_matches": history,
                }},
            )
        )
        low = forecast(
            replace(
                base,
                sources={"strength_model": {
                    "home_team_id": 1,
                    "away_team_id": 2,
                    "candidate_league_id": 20,
                    "home_recent_matches": history,
                }},
            )
        )

        self.assertGreater(high.league_goal_rate, low.league_goal_rate)
        self.assertGreater(high.home_xg + high.away_xg, low.home_xg + low.away_xg)

    def test_neutral_ground_removes_fitted_home_advantage(self) -> None:
        kickoff = datetime(2026, 9, 10, tzinfo=timezone.utc)
        history = [
            self._history_row(index, kickoff - timedelta(days=index * 6), 1, 2, 1.7, 1.1)
            for index in range(1, 17)
        ]
        source = {
            "home_team_id": 1,
            "away_team_id": 2,
            "candidate_league_id": 10,
            "home_recent_matches": history,
        }
        base = replace(load_issue("data/sample_issue.json").matches[0], kickoff=kickoff)

        ordinary = forecast(replace(base, sources={"strength_model": source}))
        neutral = forecast(replace(base, sources={"strength_model": {**source, "neutral_venue": True}}))

        self.assertGreater(ordinary.home_advantage, 1.0)
        self.assertEqual(neutral.home_advantage, 1.0)
        self.assertLess(neutral.home_xg, ordinary.home_xg)

    def test_venue_win_rates_are_not_applied_again_after_model_fusion(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
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
        without_venue = replace(venue_match, sources={})

        prediction = predict_match(venue_match)
        baseline = predict_match(without_venue)

        self.assertEqual(prediction.probabilities, baseline.probabilities)
        self.assertFalse(any("同场地近期表现" in reason for reason in prediction.reasons))

    def test_injury_and_schedule_do_not_modify_dixon_coles_twice(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        source = {
            "home_xg_for": 1.6,
            "home_xg_against": 1.0,
            "away_xg_for": 1.1,
            "away_xg_against": 1.4,
            "home_xg_matches": 8,
            "away_xg_matches": 8,
        }
        baseline = forecast(replace(match, sources={"strength_model": source}))
        stressed = forecast(replace(
            match,
            signals=replace(
                match.signals,
                home_injury_impact=0.45,
                away_injury_impact=0.30,
                schedule_pressure_home=0.40,
                schedule_pressure_away=0.35,
            ),
            sources={"strength_model": source},
        ))

        self.assertEqual(stressed.home_xg, baseline.home_xg)
        self.assertEqual(stressed.away_xg, baseline.away_xg)
        self.assertEqual(stressed.probabilities, baseline.probabilities)

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
        self.assertFalse(any("同场地近期表现" in reason for reason in prediction.reasons))

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

    def test_fitted_model_exposes_low_score_and_league_draw_audit(self) -> None:
        kickoff = datetime(2026, 9, 10, tzinfo=timezone.utc)
        history = []
        for index in range(1, 17):
            row = self._history_row(index, kickoff - timedelta(days=index * 5), 1, 2, 1.0, 1.0)
            row["home_goals"] = 1
            row["away_goals"] = 1
            history.append(row)
        match = replace(
            load_issue("data/sample_issue.json").matches[0],
            kickoff=kickoff,
            sources={"strength_model": {
                "home_team_id": 1,
                "away_team_id": 2,
                "candidate_league_id": 10,
                "league_recent_matches": history,
            }},
        )

        result = forecast(match)

        self.assertGreater(result.league_draw_rate, 0.50)
        self.assertAlmostEqual(
            result.low_score_draw_probability,
            result.zero_zero_probability + result.one_one_probability,
            places=5,
        )
        self.assertLessEqual(result.low_score_draw_probability, result.probabilities["1"])

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

    def test_squad_paper_strength_applies_but_absence_is_not_counted_twice(self) -> None:
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
        self.assertEqual(weakened_home.home_xg, strong_home.home_xg)
        self.assertEqual(weakened_home.away_xg, strong_home.away_xg)

    def test_full_analysis_ticket_scores_reuse_final_probabilities(self) -> None:
        probabilities = {"3": 0.48, "1": 0.27, "0": 0.25}

        scores = _full_analysis_selection_scores(probabilities)

        self.assertEqual(scores, probabilities)

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

    def test_real_market_recovers_weight_from_missing_information_and_weak_math(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        neutral = replace(match, signals=type(match.signals)(), sources={})
        math_forecast = forecast(neutral)

        market, information, mathematical = _effective_blend_weights(neutral, math_forecast, None)

        self.assertAlmostEqual(information, 0.0)
        self.assertAlmostEqual(mathematical, 0.12 * 0.30)
        self.assertAlmostEqual(market, 1.0 - mathematical)

    def test_market_anchor_caps_every_outcome_shift(self) -> None:
        market = {"3": 0.60, "1": 0.25, "0": 0.15}

        adjusted = _cap_market_anchor_shift({"3": 0.30, "1": 0.35, "0": 0.35}, market)

        self.assertAlmostEqual(sum(adjusted.values()), 1.0)
        self.assertLessEqual(max(abs(adjusted[key] - market[key]) for key in market), 0.120001)


if __name__ == "__main__":
    unittest.main()
