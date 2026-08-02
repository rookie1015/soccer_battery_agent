import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from football_lottery_agent.experiments import (
    ExperimentSample,
    PredictionRecord,
    audit_snapshot,
    evaluate_records,
    load_active_model_weights,
    load_active_selection_policy,
    run_experiment,
    walk_forward_evaluate,
)
from football_lottery_agent.loader import load_issue


class ExperimentTests(unittest.TestCase):
    def test_snapshot_audit_separates_verified_legacy_and_late_data(self) -> None:
        issue = load_issue("data/sample_issue.json")
        first_kickoff = min(match.kickoff for match in issue.matches)

        verified = audit_snapshot(
            {"snapshot_collected_at": (first_kickoff - timedelta(hours=2)).isoformat()},
            issue.matches,
        )
        legacy = audit_snapshot({}, issue.matches)
        late = audit_snapshot(
            {"snapshot_collected_at": (first_kickoff + timedelta(minutes=1)).isoformat()},
            issue.matches,
        )

        self.assertEqual(verified[0], "verified_pre_match")
        self.assertEqual(legacy[0], "legacy_unverified")
        self.assertEqual(late[0], "post_kickoff_excluded")

    def test_metrics_cover_probability_and_special_outcomes(self) -> None:
        samples = [
            _sample("26001", 1, "3", {"3": 0.8, "1": 0.1, "0": 0.1}),
            _sample("26001", 2, "1", {"3": 0.1, "1": 0.8, "0": 0.1}),
            _sample("26001", 3, "0", {"3": 0.1, "1": 0.1, "0": 0.8}),
        ]
        records = [PredictionRecord(sample=item, probabilities=item.components["dixon_coles"]) for item in samples]

        metrics = evaluate_records(records)

        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(metrics["top2_accuracy"], 1.0)
        self.assertEqual(metrics["draw_recall"], 1.0)
        self.assertLess(metrics["brier_score"], 0.03)
        self.assertLess(metrics["log_loss"], 0.25)

    def test_walk_forward_never_trains_on_current_issue(self) -> None:
        samples = []
        for issue_index in range(4):
            issue = f"2600{issue_index + 1}"
            for seq in range(1, 4):
                samples.append(_sample(issue, seq, ("3", "1", "0")[seq - 1]))

        result = walk_forward_evaluate(samples, min_train_matches=6)

        self.assertEqual(result["fold_count"], 2)
        self.assertEqual(result["folds"][0]["test_issue"], "26003")
        self.assertEqual(result["folds"][0]["train_issues"], 2)
        self.assertEqual(result["folds"][0]["train_matches"], 6)
        self.assertEqual(result["folds"][1]["test_issue"], "26004")
        self.assertEqual(result["folds"][1]["train_issues"], 3)

    def test_only_strict_out_of_sample_results_can_activate_model(self) -> None:
        strict = []
        for issue_index in range(4):
            issue = f"2601{issue_index}"
            for seq, outcome in enumerate(("3", "1", "0"), start=1):
                strict.append(_sample(issue, seq, outcome))

        with TemporaryDirectory() as tmp, patch(
            "football_lottery_agent.experiments.load_experiment_samples",
            return_value=(strict, _audit(strict)),
        ):
            result = run_experiment(
                tmp,
                min_train_matches=6,
                min_test_matches=6,
                min_test_issues=2,
                min_brier_gain=0.001,
                promote=True,
                created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            )
            active = load_active_model_weights(tmp)
            active_policy = load_active_selection_policy(tmp)

        self.assertEqual(result["promotion"]["status"], "promoted")
        self.assertIsNotNone(active)
        self.assertIsNotNone(active_policy)
        self.assertGreater(active["dixon_coles"], active["odds"])
        self.assertTrue(Path(result["artifacts"]["json"]).name.endswith("pure-1x2-v1.json"))

    def test_legacy_samples_remain_exploratory_and_cannot_promote(self) -> None:
        legacy = [
            ExperimentSample(
                **{
                    **_sample("26020", seq, outcome).__dict__,
                    "snapshot_status": "legacy_unverified",
                }
            )
            for seq, outcome in enumerate(("3", "1", "0"), start=1)
        ]
        with TemporaryDirectory() as tmp, patch(
            "football_lottery_agent.experiments.load_experiment_samples",
            return_value=(legacy, _audit(legacy)),
        ):
            result = run_experiment(
                tmp,
                min_train_matches=1,
                min_test_matches=1,
                min_test_issues=1,
                promote=True,
            )

        self.assertEqual(result["strict"]["sample_count"], 0)
        self.assertEqual(result["exploratory"]["sample_count"], 3)
        self.assertEqual(result["promotion"]["status"], "collecting")
        self.assertIsNone(load_active_model_weights(tmp))


def _sample(
    issue: str,
    seq: int,
    outcome: str,
    dixon: dict[str, float] | None = None,
) -> ExperimentSample:
    wrong = {"3": "1", "1": "0", "0": "3"}[outcome]
    odds = {item: 0.2 for item in ("3", "1", "0")}
    odds[wrong] = 0.6
    signals = {item: 0.1 for item in ("3", "1", "0")}
    signals[wrong] = 0.8
    dixon_values = dixon or {item: (0.9 if item == outcome else 0.05) for item in ("3", "1", "0")}
    return ExperimentSample(
        issue=issue,
        seq=seq,
        kickoff=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=int(issue[-2:]), minutes=seq),
        league="测试联赛",
        outcome=outcome,
        components={"odds": odds, "signals": signals, "dixon_coles": dixon_values},
        data_quality="strength",
        snapshot_status="verified_pre_match",
    )


def _audit(samples: list[ExperimentSample]) -> dict:
    strict = sum(item.snapshot_status == "verified_pre_match" for item in samples)
    exploratory = sum(item.snapshot_status != "post_kickoff_excluded" for item in samples)
    return {
        "issue_status_counts": {},
        "issues": [],
        "skipped": {},
        "strict_sample_count": strict,
        "exploratory_sample_count": exploratory,
        "excluded_sample_count": len(samples) - exploratory,
    }


if __name__ == "__main__":
    unittest.main()
