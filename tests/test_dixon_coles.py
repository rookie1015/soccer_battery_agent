import unittest
from dataclasses import replace

from football_lottery_agent.dixon_coles import forecast
from football_lottery_agent.loader import load_issue
from football_lottery_agent.models import Match
from football_lottery_agent.predictor import predict_match


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


if __name__ == "__main__":
    unittest.main()
