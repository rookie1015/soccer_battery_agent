import unittest
from dataclasses import replace

from football_lottery_agent.dixon_coles import forecast
from football_lottery_agent.loader import load_issue
from football_lottery_agent.models import Match
from football_lottery_agent.predictor import _blend_weights, _select_picks, _signal_scores, predict_match


class DixonColesTests(unittest.TestCase):
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

    def test_predictor_includes_math_model_reason(self) -> None:
        prediction = predict_match(load_issue("data/sample_issue.json").matches[0])

        self.assertTrue(any("Dixon-Coles" in reason for reason in prediction.reasons))

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
