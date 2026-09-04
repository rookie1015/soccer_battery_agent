from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Iterable, Mapping

from .dixon_coles import DixonColesForecast
from .models import Match


OUTCOMES = ("3", "1", "0")
MAX_DRAW_LOGIT_SHIFT = 0.055
DEFAULT_DRAW_CALIBRATION_COEFFICIENTS = {
    "draw_movement": 0.018,
    "shallow_handicap": 0.022,
    "low_total": 0.020,
    "total_drop": 0.016,
}


@dataclass(frozen=True)
class DrawCalibrationProfile:
    """A bounded residual draw correction with an explicit ownership boundary.

    Market-structure features create the correction. Dixon-Coles low-score
    mass and the fitted league draw rate only control how much of that
    correction is trusted; they never add a second mathematical correction.
    """

    features: dict[str, float]
    available: dict[str, bool]
    contributions: dict[str, float]
    logit_shift: float
    corrections: dict[str, float]
    evidence: tuple[str, ...]


def build_draw_calibration_profile(
    match: Match,
    mathematical: DixonColesForecast,
    coefficients: Mapping[str, float] | None = None,
) -> DrawCalibrationProfile:
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    movement = market.get("market_movement") if isinstance(market.get("market_movement"), dict) else {}

    draw_movement = _number(movement.get("1"))
    handicap = _first_number(market, "asian_current_line", "spread_home_point")
    total = _first_number(market, "total_points")
    total_movement = _first_number(
        market,
        "total_line_movement",
        "total_points_movement",
    )
    if total_movement is None:
        opening_total = _first_number(market, "total_opening_points", "opening_total_points")
        if total is not None and opening_total is not None:
            total_movement = total - opening_total

    features = {
        "draw_movement": _clamp((draw_movement or 0.0) / 0.02, -1.0, 1.0),
        "shallow_handicap": (
            _clamp((0.75 - abs(handicap)) / 0.75, 0.0, 1.0)
            if handicap is not None
            else 0.0
        ),
        "low_total": _clamp((2.65 - total) / 0.65, -1.0, 1.0) if total is not None else 0.0,
        "total_drop": _clamp(-total_movement / 0.25, -1.0, 1.0) if total_movement is not None else 0.0,
        "low_score_support": _clamp(
            (mathematical.low_score_draw_probability - 0.18) / 0.10,
            -1.0,
            1.0,
        ),
        "league_draw_support": _clamp(
            (mathematical.league_draw_rate - 0.27) / 0.08,
            -1.0,
            1.0,
        ),
    }
    available = {
        "draw_movement": draw_movement is not None,
        "shallow_handicap": handicap is not None,
        "low_total": total is not None,
        "total_drop": total_movement is not None,
        "low_score_support": mathematical.data_quality != "signal_fallback",
        "league_draw_support": mathematical.data_quality in {"fitted", "partial_fitted"},
    }

    values = dict(DEFAULT_DRAW_CALIBRATION_COEFFICIENTS)
    if coefficients:
        for name in values:
            try:
                values[name] = _clamp(float(coefficients[name]), -0.08, 0.08)
            except (KeyError, TypeError, ValueError):
                continue
    contributions = {
        name: values[name] * features[name] if available[name] else 0.0
        for name in values
    }
    structural_shift = sum(contributions.values())

    # Low-score mass and league draw history come from the same historical
    # graph as Dixon-Coles. They therefore corroborate the independent market
    # structure instead of creating another additive signal.
    quality = _clamp(mathematical.data_quality_score, 0.0, 1.0)
    low_score_support = features["low_score_support"] * quality if available["low_score_support"] else 0.0
    league_support = features["league_draw_support"] * quality if available["league_draw_support"] else 0.0
    corroboration = _clamp(0.75 + 0.15 * low_score_support + 0.10 * league_support, 0.50, 1.0)
    logit_shift = _clamp(structural_shift * corroboration, -MAX_DRAW_LOGIT_SHIFT, MAX_DRAW_LOGIT_SHIFT)
    corrections = {
        "3": -0.5 * logit_shift,
        "1": logit_shift,
        "0": -0.5 * logit_shift,
    }
    evidence = _evidence(
        draw_movement=draw_movement,
        handicap=handicap,
        total=total,
        total_movement=total_movement,
        mathematical=mathematical,
        available=available,
    )
    return DrawCalibrationProfile(
        features={key: round(value, 6) for key, value in features.items()},
        available=available,
        contributions={key: round(value, 6) for key, value in contributions.items()},
        logit_shift=round(logit_shift, 6),
        corrections={key: round(value, 6) for key, value in corrections.items()},
        evidence=evidence,
    )


def draw_calibration_corrections_from_features(
    features: Mapping[str, float],
    available: Mapping[str, bool],
    *,
    mathematical_quality: float,
    coefficients: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Reproduce the production correction inside walk-forward experiments."""
    values = dict(DEFAULT_DRAW_CALIBRATION_COEFFICIENTS)
    if coefficients:
        for name in values:
            try:
                values[name] = _clamp(float(coefficients[name]), -0.08, 0.08)
            except (KeyError, TypeError, ValueError):
                continue
    structural_shift = sum(
        values[name] * float(features.get(name, 0.0))
        for name in values
        if available.get(name, False)
    )
    quality = _clamp(float(mathematical_quality), 0.0, 1.0)
    low_score_support = float(features.get("low_score_support", 0.0)) * quality if available.get("low_score_support") else 0.0
    league_support = float(features.get("league_draw_support", 0.0)) * quality if available.get("league_draw_support") else 0.0
    corroboration = _clamp(0.75 + 0.15 * low_score_support + 0.10 * league_support, 0.50, 1.0)
    shift = _clamp(structural_shift * corroboration, -MAX_DRAW_LOGIT_SHIFT, MAX_DRAW_LOGIT_SHIFT)
    return {"3": -0.5 * shift, "1": shift, "0": -0.5 * shift}


def fit_draw_calibration_coefficients(
    samples: Iterable[
        tuple[Mapping[str, float], Mapping[str, bool], Mapping[str, float], str, float]
    ],
    *,
    l2: float = 0.35,
    iterations: int = 500,
) -> dict[str, float]:
    """Fit draw-vs-non-draw residuals without peeking at test issues."""
    items = [item for item in samples if item[3] in OUTCOMES]
    if not items:
        return dict(DEFAULT_DRAW_CALIBRATION_COEFFICIENTS)
    coefficients = dict(DEFAULT_DRAW_CALIBRATION_COEFFICIENTS)
    for iteration in range(iterations):
        gradients = {
            name: l2 * (coefficients[name] - DEFAULT_DRAW_CALIBRATION_COEFFICIENTS[name])
            for name in coefficients
        }
        for features, available, baseline, actual, quality in items:
            effective = _effective_structural_features(features, available, quality)
            corrections = draw_calibration_corrections_from_features(
                features,
                available,
                mathematical_quality=quality,
                coefficients=coefficients,
            )
            probabilities = _apply_corrections(baseline, corrections)
            draw_error = probabilities["1"] - float(actual == "1")
            for name in coefficients:
                gradients[name] += 1.5 * draw_error * effective[name] / len(items)
        learning_rate = 0.16 / (1.0 + iteration / 160.0)
        for name in coefficients:
            coefficients[name] = _clamp(
                coefficients[name] - learning_rate * gradients[name],
                -0.08,
                0.08,
            )
    return {name: round(value, 4) for name, value in coefficients.items()}


def valid_draw_calibration_coefficients(value: Mapping[str, float] | None) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {
            name: _clamp(float(value[name]), -0.08, 0.08)
            for name in DEFAULT_DRAW_CALIBRATION_COEFFICIENTS
        }
    except (KeyError, TypeError, ValueError):
        return None


def _effective_structural_features(
    features: Mapping[str, float],
    available: Mapping[str, bool],
    mathematical_quality: float,
) -> dict[str, float]:
    quality = _clamp(float(mathematical_quality), 0.0, 1.0)
    low_score_support = float(features.get("low_score_support", 0.0)) * quality if available.get("low_score_support") else 0.0
    league_support = float(features.get("league_draw_support", 0.0)) * quality if available.get("league_draw_support") else 0.0
    corroboration = _clamp(0.75 + 0.15 * low_score_support + 0.10 * league_support, 0.50, 1.0)
    return {
        name: float(features.get(name, 0.0)) * corroboration if available.get(name, False) else 0.0
        for name in DEFAULT_DRAW_CALIBRATION_COEFFICIENTS
    }


def _apply_corrections(
    baseline: Mapping[str, float],
    corrections: Mapping[str, float],
) -> dict[str, float]:
    scores = {
        outcome: float(baseline.get(outcome, 0.0)) * exp(float(corrections.get(outcome, 0.0)))
        for outcome in OUTCOMES
    }
    total = sum(scores.values())
    return {outcome: scores[outcome] / total for outcome in OUTCOMES}


def _evidence(
    *,
    draw_movement: float | None,
    handicap: float | None,
    total: float | None,
    total_movement: float | None,
    mathematical: DixonColesForecast,
    available: Mapping[str, bool],
) -> tuple[str, ...]:
    evidence: list[str] = []
    if draw_movement is not None:
        evidence.append(f"欧赔平局概率较初盘 {draw_movement:+.1%}")
    if handicap is not None:
        evidence.append(f"亚洲盘 {handicap:+g}")
    if total is not None:
        total_text = f"大小球 {total:g}"
        if total_movement is not None:
            total_text += f"（较初盘 {total_movement:+g}）"
        evidence.append(total_text)
    if available.get("low_score_support"):
        evidence.append(
            f"0:0/1:1 合计 {mathematical.low_score_draw_probability:.1%}"
            f"（{mathematical.zero_zero_probability:.1%}/{mathematical.one_one_probability:.1%}）"
        )
    if available.get("league_draw_support"):
        evidence.append(f"联赛平局基准 {mathematical.league_draw_rate:.1%}")
    return tuple(evidence)


def _first_number(values: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _number(values.get(name))
        if value is not None:
            return value
    return None


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
