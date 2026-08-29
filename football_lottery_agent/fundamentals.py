from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from typing import Iterable, Mapping

from .models import Match


OUTCOMES = ("3", "1", "0")
EDGE_FEATURES = ("form", "motivation", "injury", "schedule")
DRAW_FEATURES = ("draw_balance", "low_total", "draw_rate")
FEATURE_NAMES = (*EDGE_FEATURES, *DRAW_FEATURES)

# Conservative production priors.  They are deliberately small because the
# market is the probability baseline.  Walk-forward experiments may learn a
# replacement, but a candidate never becomes active without promotion gates.
DEFAULT_FUNDAMENTAL_COEFFICIENTS = {
    "form": 0.20,
    "motivation": 0.05,
    "injury": 0.04,
    "schedule": 0.0,
    "draw_balance": 0.03,
    "low_total": 0.04,
    "draw_rate": 0.03,
}
MAX_FUNDAMENTAL_LOGIT_SHIFT = 0.12
MAX_MATHEMATICAL_LOGIT_SHIFT = 0.08


@dataclass(frozen=True)
class FundamentalProfile:
    """Auditable, reliability-adjusted pre-match fundamental features."""

    raw_features: dict[str, float]
    reliabilities: dict[str, float]
    features: dict[str, float]


def build_fundamental_profile(match: Match) -> FundamentalProfile:
    signals = match.signals
    form_edge = signals.home_form - signals.away_form
    motivation_edge = signals.home_motivation - signals.away_motivation
    injury_edge = signals.away_injury_impact - signals.home_injury_impact
    schedule_edge = signals.schedule_pressure_away - signals.schedule_pressure_home

    balance = max(0.0, 1.0 - abs(form_edge))
    expected_total, recent_draw_rate = _draw_context(match)
    raw = {
        "form": _clamp(form_edge, -1.0, 1.0),
        "motivation": _clamp(motivation_edge, -1.0, 1.0),
        "injury": _clamp(injury_edge, -1.0, 1.0),
        "schedule": _clamp(schedule_edge, -1.0, 1.0),
        # Centre draw features so that missing/ordinary evidence makes no
        # correction instead of silently becoming a generic draw prior.
        "draw_balance": _clamp((balance - 0.50) * 2.0, -1.0, 1.0),
        "low_total": 0.0 if expected_total is None else _clamp(2.35 - expected_total, -1.0, 1.0),
        "draw_rate": (
            0.0
            if recent_draw_rate is None
            else _clamp((recent_draw_rate - 0.27) / 0.20, -1.0, 1.0)
        ),
    }
    reliability = _feature_reliabilities(match, raw)
    effective = {name: raw[name] * reliability[name] for name in FEATURE_NAMES}
    return FundamentalProfile(raw_features=raw, reliabilities=reliability, features=effective)


def fundamental_corrections(
    profile: FundamentalProfile,
    coefficients: Mapping[str, float] | None = None,
    *,
    scale: float = 1.0,
) -> dict[str, float]:
    values = valid_fundamental_coefficients(coefficients) or dict(DEFAULT_FUNDAMENTAL_COEFFICIENTS)
    edge = sum(values[name] * profile.features[name] for name in EDGE_FEATURES)
    draw = sum(values[name] * profile.features[name] for name in DRAW_FEATURES)
    raw = {
        "3": 0.5 * edge - 0.25 * draw,
        "1": 0.5 * draw,
        "0": -0.5 * edge - 0.25 * draw,
    }
    limit = MAX_FUNDAMENTAL_LOGIT_SHIFT
    return {outcome: _clamp(raw[outcome] * max(0.0, scale), -limit, limit) for outcome in OUTCOMES}


def apply_logit_corrections(
    baseline: Mapping[str, float],
    corrections: Mapping[str, float],
) -> dict[str, float]:
    scores = {
        outcome: log(max(float(baseline.get(outcome, 0.0)), 1e-9)) + float(corrections.get(outcome, 0.0))
        for outcome in OUTCOMES
    }
    peak = max(scores.values())
    values = {outcome: exp(score - peak) for outcome, score in scores.items()}
    total = sum(values.values())
    return {outcome: values[outcome] / total for outcome in OUTCOMES}


def mathematical_corrections(
    market: Mapping[str, float],
    mathematical: Mapping[str, float],
    *,
    strength: float,
    quality: str,
) -> dict[str, float]:
    # A form-based fallback is not independent mathematical evidence and must
    # not count the same recent-form signal twice.
    if quality == "signal_fallback" or strength <= 0:
        return {outcome: 0.0 for outcome in OUTCOMES}
    quality_multiplier = 0.35 if quality == "hybrid_fallback" else 1.0
    raw = {
        outcome: strength
        * quality_multiplier
        * log(max(float(mathematical.get(outcome, 0.0)), 1e-9) / max(float(market.get(outcome, 0.0)), 1e-9))
        for outcome in OUTCOMES
    }
    centre = sum(raw.values()) / len(raw)
    return {
        outcome: _clamp(raw[outcome] - centre, -MAX_MATHEMATICAL_LOGIT_SHIFT, MAX_MATHEMATICAL_LOGIT_SHIFT)
        for outcome in OUTCOMES
    }


def fit_fundamental_coefficients(
    samples: Iterable[tuple[Mapping[str, float], Mapping[str, float], str]],
    *,
    l2: float = 0.18,
    iterations: int = 700,
) -> dict[str, float]:
    """Fit market-offset multinomial coefficients with conservative shrinkage."""

    items = [(dict(features), dict(market), outcome) for features, market, outcome in samples if outcome in OUTCOMES]
    if not items:
        return dict(DEFAULT_FUNDAMENTAL_COEFFICIENTS)
    coefficients = {name: 0.0 for name in FEATURE_NAMES}
    for iteration in range(iterations):
        gradients = {name: l2 * coefficients[name] for name in FEATURE_NAMES}
        for features, market, actual in items:
            vectors = _feature_vectors(features)
            corrections = {
                outcome: sum(coefficients[name] * vectors[name][outcome] for name in FEATURE_NAMES)
                for outcome in OUTCOMES
            }
            probabilities = apply_logit_corrections(market, corrections)
            for name in FEATURE_NAMES:
                gradients[name] += sum(
                    (probabilities[outcome] - float(outcome == actual)) * vectors[name][outcome]
                    for outcome in OUTCOMES
                ) / len(items)
        learning_rate = 0.22 / (1.0 + iteration / 180.0)
        for name in FEATURE_NAMES:
            coefficients[name] = _clamp(coefficients[name] - learning_rate * gradients[name], -0.60, 0.60)
    return {name: round(coefficients[name], 4) for name in FEATURE_NAMES}


def predict_with_fundamental_coefficients(
    market: Mapping[str, float],
    features: Mapping[str, float],
    coefficients: Mapping[str, float],
) -> dict[str, float]:
    vectors = _feature_vectors(features)
    corrections = {
        outcome: _clamp(
            sum(float(coefficients.get(name, 0.0)) * vectors[name][outcome] for name in FEATURE_NAMES),
            -MAX_FUNDAMENTAL_LOGIT_SHIFT,
            MAX_FUNDAMENTAL_LOGIT_SHIFT,
        )
        for outcome in OUTCOMES
    }
    return apply_logit_corrections(market, corrections)


def valid_fundamental_coefficients(value: Mapping[str, float] | None) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {name: _clamp(float(value[name]), -0.60, 0.60) for name in FEATURE_NAMES}
    except (KeyError, TypeError, ValueError):
        return None


def _feature_vectors(features: Mapping[str, float]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for name in EDGE_FEATURES:
        value = float(features.get(name, 0.0))
        result[name] = {"3": 0.5 * value, "1": 0.0, "0": -0.5 * value}
    for name in DRAW_FEATURES:
        value = float(features.get(name, 0.0))
        result[name] = {"3": -0.25 * value, "1": 0.5 * value, "0": -0.25 * value}
    return result


def _feature_reliabilities(match: Match, raw: Mapping[str, float]) -> dict[str, float]:
    audit = match.sources.get("collection_audit") if isinstance(match.sources, dict) else None
    if not isinstance(audit, dict) or audit.get("mode") != "full":
        return {
            "form": 0.45 if abs(raw["form"]) >= 0.02 else 0.0,
            "motivation": 0.35 if abs(raw["motivation"]) >= 0.02 else 0.0,
            "injury": 0.40 if abs(raw["injury"]) >= 0.02 else 0.0,
            "schedule": 0.35 if abs(raw["schedule"]) >= 0.02 else 0.0,
            "draw_balance": 0.35,
            "low_total": 0.40 if raw["low_total"] else 0.0,
            "draw_rate": 0.35 if raw["draw_rate"] else 0.0,
        }

    strength = _audit_section(audit, "strength")
    intelligence = _audit_section(audit, "intelligence")
    injuries = _audit_section(audit, "injuries")
    history = _audit_section(audit, "history")
    schedule = _audit_section(audit, "schedule")
    xg = _audit_section(audit, "xg")
    totals = _audit_section(audit, "totals")
    strength_status = str(strength.get("status") or "")
    history_available = history.get("status") == "available" and _count(history) > 0
    form_reliability = {
        "complete": 0.90,
        "partial": 0.65,
    }.get(strength_status, 0.45 if history_available else 0.0)
    intelligence_count = _count(intelligence)
    injury_count = _count(injuries)
    motivation_reliability = (
        min(0.80, 0.42 + 0.025 * intelligence_count)
        if intelligence.get("status") == "available" and intelligence_count
        else 0.0
    )
    injury_reliability = (
        min(0.90, 0.50 + 0.04 * injury_count)
        if injuries.get("status") == "available" and injury_count
        else 0.0
    )
    xg_status = str(xg.get("status") or "")
    total_reliability = (
        0.85
        if xg_status == "complete"
        else 0.65
        if xg_status == "partial"
        else 0.55
        if totals.get("status") == "available"
        else 0.0
    )
    history_reliability = 0.65 if history_available else 0.0
    schedule_reliability = 0.70 if schedule.get("status") == "available" else 0.0
    return {
        "form": form_reliability if abs(raw["form"]) >= 0.02 else 0.0,
        "motivation": motivation_reliability if abs(raw["motivation"]) >= 0.02 else 0.0,
        "injury": injury_reliability if abs(raw["injury"]) >= 0.02 else 0.0,
        "schedule": schedule_reliability if abs(raw["schedule"]) >= 0.02 else 0.0,
        "draw_balance": form_reliability,
        "low_total": total_reliability if raw["low_total"] else 0.0,
        "draw_rate": history_reliability if raw["draw_rate"] else 0.0,
    }


def _draw_context(match: Match) -> tuple[float | None, float | None]:
    source = match.sources.get("strength_model") if isinstance(match.sources, dict) else {}
    source = source if isinstance(source, dict) else {}
    expected_total = None
    for prefix in ("xg", "goals"):
        values = tuple(
            _positive_number(source.get(key))
            for key in (
                f"home_{prefix}_for",
                f"home_{prefix}_against",
                f"away_{prefix}_for",
                f"away_{prefix}_against",
            )
        )
        if None not in values:
            home_for, home_against, away_for, away_against = values
            expected_total = (home_for * away_against) ** 0.5 + (away_for * home_against) ** 0.5
            break
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    if expected_total is None:
        expected_total = _positive_number(market.get("total_points"))

    draw_rates = [
        value
        for value in (
            _probability(source.get("home_draw_rate")),
            _probability(source.get("away_draw_rate")),
        )
        if value is not None
    ]
    return expected_total, (sum(draw_rates) / len(draw_rates) if draw_rates else None)


def _audit_section(audit: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = audit.get(name)
    return value if isinstance(value, Mapping) else {}


def _count(section: Mapping[str, object]) -> int:
    try:
        return max(0, int(section.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _probability(value: object) -> float | None:
    try:
        return _clamp(float(value), 0.0, 1.0)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
