from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Iterable

from .dixon_coles import forecast as dixon_coles_forecast
from .history import load_history_entries
from .loader import load_issue
from .models import Match
from .predictor import _odds_to_probabilities, _signal_scores


OUTCOMES = ("3", "1", "0")
MIN_TRAINING_SAMPLES = 84
DEFAULT_WEIGHTS = {"odds": 0.55, "signals": 0.22, "dixon_coles": 0.23}


@dataclass(frozen=True)
class CalibrationSample:
    kickoff: datetime
    outcome: str
    components: dict[str, dict[str, float]]


def build_calibration(work_dir: str | Path) -> dict[str, object]:
    """Build the production-facing status from the versioned experiment.

    ``calibrate`` and ``fit_weights`` below remain available for legacy
    exploratory comparisons, but their linear-blend weights are not production
    parameters for the market-residual model.
    """
    # Local import avoids a module cycle: experiments retains the legacy
    # calibration types solely for old/synthetic comparison rows.
    from .experiments import build_current_model_status

    root = Path(work_dir)
    result = build_current_model_status(root)
    path = root / "reports" / "model_calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_review_samples(root: Path) -> list[CalibrationSample]:
    history_dir = root / "reports" / "history"
    latest_reviews: dict[str, dict[str, str]] = {}
    for entry in load_history_entries(history_dir):
        if entry.get("kind") != "review":
            continue
        if "play_type=choose9" in str(entry.get("condition_key") or ""):
            continue
        issue = str(entry.get("issue") or "").strip()
        if issue and issue not in latest_reviews:
            latest_reviews[issue] = entry

    samples: list[CalibrationSample] = []
    for issue, entry in latest_reviews.items():
        issue_path = _history_snapshot_path(history_dir, entry) or root / "data" / f"{_slug(issue)}_issue.json"
        markdown = _history_markdown_path(history_dir, entry)
        if not issue_path.exists() or not markdown.exists():
            continue
        outcomes = _review_outcomes(markdown)
        if not outcomes:
            continue
        try:
            loaded = load_issue(issue_path)
        except (OSError, ValueError, KeyError):
            continue
        if not _verified_pre_match_snapshot(loaded.metadata, loaded.matches):
            continue
        for match in loaded.matches:
            outcome = outcomes.get(match.seq)
            if outcome:
                samples.append(
                    CalibrationSample(
                        kickoff=match.kickoff,
                        outcome=outcome,
                        components=_component_probabilities(match),
                    )
                )
    return sorted(samples, key=lambda sample: sample.kickoff)


def calibrate(samples: Iterable[CalibrationSample]) -> dict[str, object]:
    ordered = sorted(samples, key=lambda sample: sample.kickoff)
    sample_count = len(ordered)
    if sample_count < MIN_TRAINING_SAMPLES:
        return {
            "status": "collecting",
            "sample_count": sample_count,
            "minimum_samples": MIN_TRAINING_SAMPLES,
            "weights": DEFAULT_WEIGHTS,
            "message": "历史样本不足，继续收集真实复盘后再学习数学模型权重。",
        }

    rolling_scores: list[float] = []
    start = MIN_TRAINING_SAMPLES
    for index in range(start, sample_count, 14):
        weights = fit_weights(ordered[:index])
        rolling_scores.append(_brier_score(ordered[index : min(index + 14, sample_count)], weights))
    weights = fit_weights(ordered)
    return {
        "status": "calibrated",
        "sample_count": sample_count,
        "minimum_samples": MIN_TRAINING_SAMPLES,
        "weights": weights,
        "rolling_brier_score": round(sum(rolling_scores) / len(rolling_scores), 4) if rolling_scores else None,
        "message": "权重由历史复盘的滚动 Brier Score 回测学习。",
    }


def fit_weights(samples: Iterable[CalibrationSample]) -> dict[str, float]:
    items = list(samples)
    if not items:
        return dict(DEFAULT_WEIGHTS)
    best = dict(DEFAULT_WEIGHTS)
    best_score = _brier_score(items, best)
    for odds_step, signals_step in product(range(0, 21), repeat=2):
        odds = odds_step / 20.0
        signals = signals_step / 20.0
        dixon_coles = 1.0 - odds - signals
        if dixon_coles < 0.0:
            continue
        weights = {"odds": odds, "signals": signals, "dixon_coles": dixon_coles}
        score = _brier_score(items, weights)
        if score < best_score:
            best, best_score = weights, score
    return {name: round(value, 2) for name, value in best.items()}


def _brier_score(samples: Iterable[CalibrationSample], weights: dict[str, float]) -> float:
    items = list(samples)
    if not items:
        return 1.0
    total = 0.0
    for sample in items:
        for outcome in OUTCOMES:
            probability = sum(weights[name] * sample.components[name][outcome] for name in weights)
            total += (probability - float(outcome == sample.outcome)) ** 2
    return total / (len(items) * len(OUTCOMES))


def _component_probabilities(match: Match) -> dict[str, dict[str, float]]:
    return {
        "odds": _odds_to_probabilities(match),
        "signals": _signal_scores(match),
        "dixon_coles": dixon_coles_forecast(match).probabilities,
    }


def _review_outcomes(path: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        label = cells[3]
        outcome = {"主胜": "3", "平": "1", "客胜": "0"}.get(label)
        if outcome:
            result[int(cells[0])] = outcome
    return result


def _history_markdown_path(history_dir: Path, entry: dict[str, str]) -> Path:
    return history_dir / str(entry.get("markdown") or "")


def _history_snapshot_path(history_dir: Path, entry: dict[str, str]) -> Path | None:
    relative = str(entry.get("snapshot") or "").strip()
    if not relative:
        return None
    path = history_dir / relative
    return path if path.exists() else None


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    return {key: value / total for key, value in values.items()} if total else {key: 1 / 3 for key in values}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "issue"


def _verified_pre_match_snapshot(metadata: dict[str, object], matches: tuple[Match, ...]) -> bool:
    value = str(metadata.get("snapshot_collected_at") or "").strip()
    if not value or not matches:
        return False
    try:
        collected = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if collected.tzinfo is None:
        collected = collected.replace(tzinfo=timezone.utc)
    first_kickoff = min(
        match.kickoff.replace(tzinfo=timezone.utc) if match.kickoff.tzinfo is None else match.kickoff.astimezone(timezone.utc)
        for match in matches
    )
    return collected.astimezone(timezone.utc) < first_kickoff
