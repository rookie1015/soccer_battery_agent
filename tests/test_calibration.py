import unittest
from datetime import datetime, timedelta

from football_lottery_agent.calibration import (
    DEFAULT_WEIGHTS,
    MIN_TRAINING_SAMPLES,
    CalibrationSample,
    calibrate,
    fit_weights,
)


class CalibrationTests(unittest.TestCase):
    def test_calibration_keeps_default_weights_when_history_is_too_small(self) -> None:
        result = calibrate([])

        self.assertEqual(result["status"], "collecting")
        self.assertEqual(result["weights"], DEFAULT_WEIGHTS)
        self.assertEqual(result["minimum_samples"], MIN_TRAINING_SAMPLES)

    def test_fit_weights_favors_component_with_lower_brier_error(self) -> None:
        start = datetime(2026, 1, 1)
        samples = [
            CalibrationSample(
                kickoff=start + timedelta(days=index),
                outcome="3",
                components={
                    "odds": {"3": 0.34, "1": 0.33, "0": 0.33},
                    "signals": {"3": 0.20, "1": 0.40, "0": 0.40},
                    "dixon_coles": {"3": 0.82, "1": 0.10, "0": 0.08},
                },
            )
            for index in range(MIN_TRAINING_SAMPLES)
        ]

        weights = fit_weights(samples)

        self.assertGreater(weights["dixon_coles"], weights["odds"])
        self.assertGreater(weights["dixon_coles"], weights["signals"])


if __name__ == "__main__":
    unittest.main()
