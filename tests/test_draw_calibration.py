import unittest
from dataclasses import replace

from football_lottery_agent.dixon_coles import DixonColesForecast
from football_lottery_agent.draw_calibration import (
    MAX_DRAW_LOGIT_SHIFT,
    build_draw_calibration_profile,
    draw_calibration_corrections_from_features,
)
from football_lottery_agent.fundamentals import apply_logit_corrections
from football_lottery_agent.loader import load_issue
from football_lottery_agent.predictor import predict_match


class DrawCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.match = load_issue("data/sample_issue.json").matches[0]
        self.math = DixonColesForecast(
            home_xg=1.05,
            away_xg=0.95,
            probabilities={"3": 0.37, "1": 0.34, "0": 0.29},
            data_quality="fitted",
            data_quality_score=0.8,
            zero_zero_probability=0.15,
            one_one_probability=0.14,
            low_score_draw_probability=0.29,
            league_draw_rate=0.31,
        )

    def test_shallow_falling_total_and_draw_movement_raise_draw(self) -> None:
        match = replace(
            self.match,
            sources={
                **self.match.sources,
                "odds_market": {
                    "market_movement": {"3": -0.01, "1": 0.02, "0": -0.01},
                    "asian_current_line": -0.25,
                    "total_points": 2.25,
                    "total_opening_points": 2.75,
                },
            },
        )

        profile = build_draw_calibration_profile(match, self.math)
        calibrated = apply_logit_corrections({"3": 0.40, "1": 0.30, "0": 0.30}, profile.corrections)

        self.assertGreater(profile.logit_shift, 0.0)
        self.assertLessEqual(profile.logit_shift, MAX_DRAW_LOGIT_SHIFT)
        self.assertGreater(calibrated["1"], 0.30)
        self.assertIn("0:0/1:1", " ".join(profile.evidence))
        self.assertIn("联赛平局基准", " ".join(profile.evidence))

    def test_rising_high_total_and_falling_draw_probability_lower_draw(self) -> None:
        match = replace(
            self.match,
            sources={
                **self.match.sources,
                "odds_market": {
                    "market_movement": {"3": 0.01, "1": -0.02, "0": 0.01},
                    "asian_current_line": -1.25,
                    "total_points": 3.25,
                    "total_opening_points": 2.75,
                },
            },
        )

        profile = build_draw_calibration_profile(match, self.math)

        self.assertLess(profile.logit_shift, 0.0)

    def test_math_history_only_corroborates_and_is_not_added_twice(self) -> None:
        match = replace(self.match, sources={**self.match.sources, "odds_market": {}})

        profile = build_draw_calibration_profile(match, self.math)

        self.assertEqual(profile.logit_shift, 0.0)
        self.assertEqual(profile.corrections, {"3": -0.0, "1": 0.0, "0": -0.0})

    def test_walk_forward_reproduction_matches_profile(self) -> None:
        match = replace(
            self.match,
            sources={
                **self.match.sources,
                "odds_market": {
                    "market_movement": {"1": 0.012},
                    "asian_current_line": 0.0,
                },
            },
        )
        profile = build_draw_calibration_profile(match, self.math)

        reproduced = draw_calibration_corrections_from_features(
            profile.features,
            profile.available,
            mathematical_quality=self.math.data_quality_score,
        )

        for outcome in ("3", "1", "0"):
            self.assertAlmostEqual(reproduced[outcome], profile.corrections[outcome], places=6)

    def test_prediction_exposes_draw_calibration_audit(self) -> None:
        match = replace(
            self.match,
            sources={
                **self.match.sources,
                "odds_market": {
                    "market_consensus": {"3": 0.39, "1": 0.31, "0": 0.30},
                    "market_movement": {"3": -0.005, "1": 0.010, "0": -0.005},
                    "asian_current_line": 0.0,
                },
            },
        )

        prediction = predict_match(match)

        self.assertEqual(set(prediction.draw_calibration_corrections), {"3", "1", "0"})
        self.assertIn("shallow_handicap", prediction.draw_calibration_features)
        self.assertTrue(any("平局独立校准" in reason for reason in prediction.reasons))


if __name__ == "__main__":
    unittest.main()
