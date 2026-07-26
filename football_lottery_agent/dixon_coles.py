from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial, log

from .models import Match


HOME_ADVANTAGE = 1.08
LOW_SCORE_RHO = -0.08
MAX_GOALS = 7
LEAGUE_RATE_PRIOR = 1.30
XG_PRIOR_WEIGHT = 2.5
GOALS_PRIOR_WEIGHT = 6.0


@dataclass(frozen=True)
class DixonColesForecast:
    home_xg: float
    away_xg: float
    probabilities: dict[str, float]
    data_quality: str
    data_quality_score: float


@dataclass(frozen=True)
class _TeamRates:
    attack: float
    defence: float
    quality: str
    confidence: float


def forecast(match: Match) -> DixonColesForecast:
    """Produce an independent 3/1/0 prior from team attack/defence rates.

    When the full FotMob strength profile is present, recent xG/xGA is used.
    Simple analyses fall back to recent-form signals, keeping the model bounded
    and explicitly lower-confidence rather than silently using bookmaker odds.
    """
    source = match.sources.get("strength_model") if isinstance(match.sources, dict) else {}
    source = source if isinstance(source, dict) else {}
    home_rates = _team_rates(source, "home", match)
    away_rates = _team_rates(source, "away", match)
    home_xg = _clamp_xg((home_rates.attack * away_rates.defence) ** 0.5 * HOME_ADVANTAGE)
    away_xg = _clamp_xg((away_rates.attack * home_rates.defence) ** 0.5)

    # Keep known pre-match availability effects outside the market probabilities.
    signals = match.signals
    home_xg = _clamp_xg(home_xg * (1.0 - 0.22 * signals.home_injury_impact - 0.10 * signals.schedule_pressure_home))
    away_xg = _clamp_xg(away_xg * (1.0 - 0.22 * signals.away_injury_impact - 0.10 * signals.schedule_pressure_away))
    home_xg, away_xg = _apply_squad_strength(source, home_xg, away_xg)
    probabilities = _outcome_probabilities(home_xg, away_xg, _draw_rho(source))
    quality = _combined_quality(home_rates.quality, away_rates.quality)
    quality_score = round((home_rates.confidence + away_rates.confidence) / 2.0, 3)
    return DixonColesForecast(
        home_xg=home_xg,
        away_xg=away_xg,
        probabilities=probabilities,
        data_quality=quality,
        data_quality_score=quality_score,
    )


def _team_rates(source: dict[str, object], side: str, match: Match) -> _TeamRates:
    xg_attack = _number(source.get(f"{side}_xg_for"))
    xg_defence = _number(source.get(f"{side}_xg_against"))
    if xg_attack is not None or xg_defence is not None:
        samples = _sample_count(source.get(f"{side}_xg_matches"), default=6 if None not in (xg_attack, xg_defence) else 2)
        attack = _shrink_rate(xg_attack, samples, XG_PRIOR_WEIGHT)
        defence = _shrink_rate(xg_defence, samples, XG_PRIOR_WEIGHT)
        complete = xg_attack is not None and xg_defence is not None and samples >= 4
        confidence = min(0.92, 0.54 + 0.055 * min(samples, 7)) if complete else min(0.68, 0.42 + 0.05 * samples)
        return _TeamRates(
            attack=_clamp_xg(attack),
            defence=_clamp_xg(defence),
            quality="strength" if complete else "partial_strength",
            confidence=confidence,
        )

    goals_attack = _number(source.get(f"{side}_goals_for"))
    goals_defence = _number(source.get(f"{side}_goals_against"))
    if goals_attack is not None or goals_defence is not None:
        samples = _sample_count(source.get(f"{side}_matches_used"), default=8)
        # Goals contain finishing and goalkeeper noise. A stronger league prior
        # keeps short hot/cold streaks from becoming extreme attack/defence rates.
        attack = _shrink_rate(goals_attack, samples, GOALS_PRIOR_WEIGHT)
        defence = _shrink_rate(goals_defence, samples, GOALS_PRIOR_WEIGHT)
        return _TeamRates(
            attack=_clamp_xg(attack),
            defence=_clamp_xg(defence),
            quality="hierarchical",
            confidence=min(0.72, 0.46 + 0.018 * min(samples, 14)),
        )

    form = match.signals.home_form if side == "home" else match.signals.away_form
    opponent_form = match.signals.away_form if side == "home" else match.signals.home_form
    attack = 1.18 + (form - 0.5) * 0.70
    defence = 1.18 - (form - 0.5) * 0.45 + (opponent_form - 0.5) * 0.10
    return _TeamRates(_clamp_xg(attack), _clamp_xg(defence), "signal_fallback", 0.30)


def _shrink_rate(value: float | None, samples: int, prior_weight: float) -> float:
    if value is None:
        return LEAGUE_RATE_PRIOR
    return (value * samples + LEAGUE_RATE_PRIOR * prior_weight) / (samples + prior_weight)


def _sample_count(value: object, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _combined_quality(home: str, away: str) -> str:
    qualities = {home, away}
    if qualities == {"strength"}:
        return "strength"
    if "signal_fallback" in qualities:
        return "signal_fallback" if qualities == {"signal_fallback"} else "hybrid_fallback"
    if "hierarchical" in qualities:
        return "hierarchical"
    return "partial_strength"


def _apply_squad_strength(source: dict[str, object], home_xg: float, away_xg: float) -> tuple[float, float]:
    """Apply a deliberately small paper-squad adjustment to the xG prior."""
    home_rating = _number(source.get("home_squad_current_rating")) or _number(source.get("home_squad_paper_rating"))
    away_rating = _number(source.get("away_squad_current_rating")) or _number(source.get("away_squad_paper_rating"))
    if home_rating is None or away_rating is None:
        return home_xg, away_xg
    edge = max(-0.16, min(0.16, log(home_rating / away_rating) * 0.12))
    home_availability = _number(source.get("home_squad_availability_penalty")) or 0.0
    away_availability = _number(source.get("away_squad_availability_penalty")) or 0.0
    home_factor = 1.0 + edge - min(0.10, home_availability * 0.30)
    away_factor = 1.0 - edge - min(0.10, away_availability * 0.30)
    return _clamp_xg(home_xg * home_factor), _clamp_xg(away_xg * away_factor)


def _outcome_probabilities(
    home_xg: float,
    away_xg: float,
    rho: float = LOW_SCORE_RHO,
) -> dict[str, float]:
    outcomes = {"3": 0.0, "1": 0.0, "0": 0.0}
    total = 0.0
    for home_goals in range(MAX_GOALS + 1):
        for away_goals in range(MAX_GOALS + 1):
            probability = _poisson(home_goals, home_xg) * _poisson(away_goals, away_xg)
            probability *= _tau(home_goals, away_goals, home_xg, away_xg, rho)
            total += probability
            if home_goals > away_goals:
                outcomes["3"] += probability
            elif home_goals == away_goals:
                outcomes["1"] += probability
            else:
                outcomes["0"] += probability
    return {outcome: value / total for outcome, value in outcomes.items()} if total else {"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}


def _draw_rho(source: dict[str, object]) -> float:
    rates = [
        value
        for value in (
            _probability(source.get("home_draw_rate")),
            _probability(source.get("away_draw_rate")),
        )
        if value is not None
    ]
    if not rates:
        return LOW_SCORE_RHO
    recent_draw_rate = sum(rates) / len(rates)
    return min(-0.02, max(-0.16, LOW_SCORE_RHO - (recent_draw_rate - 0.27) * 0.25))


def _tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _poisson(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * expected_goals**goals / factorial(goals)


def _number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _probability(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, numeric))


def _clamp_xg(value: float) -> float:
    return min(3.2, max(0.35, value))
