import unittest
from dataclasses import replace

from football_lottery_agent.dixon_coles import forecast
from football_lottery_agent.fundamentals import (
    MAX_FUNDAMENTAL_LOGIT_SHIFT,
    apply_logit_corrections,
    build_fundamental_profile,
    fit_fundamental_coefficients,
    fundamental_corrections,
    mathematical_corrections,
)
from football_lottery_agent.loader import load_issue
from football_lottery_agent.models import Signals
from football_lottery_agent.predictor import predict_match


class FundamentalModelTests(unittest.TestCase):
    def test_missing_full_analysis_sources_do_not_become_real_evidence(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        audited = replace(
            match,
            signals=Signals(home_form=0.8, away_form=0.3, home_motivation=0.8, away_motivation=0.2),
            sources={
                **match.sources,
                "collection_audit": {
                    "mode": "full",
                    "strength": {"status": "missing"},
                    "intelligence": {"status": "missing"},
                    "injuries": {"status": "missing"},
                    "history": {"status": "missing"},
                    "xg": {"status": "missing"},
                    "totals": {"status": "missing"},
                },
            },
        )

        profile = build_fundamental_profile(audited)

        self.assertEqual(profile.reliabilities["motivation"], 0.0)
        self.assertEqual(profile.features["motivation"], 0.0)
        self.assertEqual(profile.reliabilities["form"], 0.0)

    def test_fundamental_market_correction_is_bounded(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        extreme = replace(match, signals=Signals(home_form=1.0, away_form=0.0, home_motivation=1.0))
        corrections = fundamental_corrections(
            build_fundamental_profile(extreme),
            {name: 0.6 for name in ("form", "motivation", "injury", "schedule", "draw_balance", "low_total", "draw_rate")},
        )

        self.assertLessEqual(max(abs(value) for value in corrections.values()), MAX_FUNDAMENTAL_LOGIT_SHIFT)
        probabilities = apply_logit_corrections({"3": 0.4, "1": 0.3, "0": 0.3}, corrections)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_signal_fallback_is_not_independent_math_evidence(self) -> None:
        match = load_issue("data/sample_issue.json").matches[0]
        math = forecast(match)

        corrections = mathematical_corrections(
            {"3": 0.4, "1": 0.3, "0": 0.3},
            math.probabilities,
            strength=0.2,
            quality=math.data_quality,
        )

        self.assertEqual(math.data_quality, "signal_fallback")
        self.assertEqual(corrections, {"3": 0.0, "1": 0.0, "0": 0.0})

    def test_rolling_fit_learns_form_direction_from_market_residuals(self) -> None:
        market = {"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}
        samples = []
        for _ in range(30):
            samples.append(({"form": 0.8}, market, "3"))
            samples.append(({"form": -0.8}, market, "0"))

        coefficients = fit_fundamental_coefficients(samples, iterations=300)

        self.assertGreater(coefficients["form"], 0.1)

    def test_prediction_exposes_feature_reliability_and_corrections(self) -> None:
        prediction = predict_match(load_issue("data/sample_issue.json").matches[0])

        self.assertIn("form", prediction.fundamental_features)
        self.assertIn("form", prediction.fundamental_reliability)
        self.assertEqual(set(prediction.fundamental_corrections), {"3", "1", "0"})
        self.assertEqual(set(prediction.mathematical_corrections), {"3", "1", "0"})


if __name__ == "__main__":
    unittest.main()
