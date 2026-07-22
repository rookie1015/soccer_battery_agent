from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial, log

from .models import Match


HOME_ADVANTAGE = 1.08
LOW_SCORE_RHO = -0.08
MAX_GOALS = 7


@dataclass(frozen=True)
class DixonColesForecast:
    home_xg: float
    away_xg: float
    probabilities: dict[str, float]
    data_quality: str


def forecast(match: Match) -> DixonColesForecast:
    """Produce an independent 3/1/0 prior from team attack/defence rates.

    When the full FotMob strength profile is present, recent xG/xGA is used.
    Simple analyses fall back to recent-form signals, keeping the model bounded
    and explicitly lower-confidence rather than silently using bookmaker odds.
    """
    source = match.sources.get("strength_model") if isinstance(match.sources, dict) else {}
    source = source if isinstance(source, dict) else {}
    home_attack, home_defence, home_quality = _team_rates(source, "home", match)
    away_attack, away_defence, away_quality = _team_rates(source, "away", match)
    home_xg = _clamp_xg((home_attack * away_defence) ** 0.5 * HOME_ADVANTAGE)
    away_xg = _clamp_xg((away_attack * home_defence) ** 0.5)

    # Keep known pre-match availability effects outside the market probabilities.
    signals = match.signals
    home_xg = _clamp_xg(home_xg * (1.0 - 0.22 * signals.home_injury_impact - 0.10 * signals.schedule_pressure_home))
    away_xg = _clamp_xg(away_xg * (1.0 - 0.22 * signals.away_injury_impact - 0.10 * signals.schedule_pressure_away))
    home_xg, away_xg = _apply_squad_strength(source, home_xg, away_xg)
    probabilities = _outcome_probabilities(home_xg, away_xg)
    quality = "strength" if home_quality and away_quality else "signal_fallback"
    return DixonColesForecast(home_xg=home_xg, away_xg=away_xg, probabilities=probabilities, data_quality=quality)


def _team_rates(source: dict[str, object], side: str, match: Match) -> tuple[float, float, bool]:
    attack = _number(source.get(f"{side}_xg_for")) or _number(source.get(f"{side}_goals_for"))
    defence = _number(source.get(f"{side}_xg_against")) or _number(source.get(f"{side}_goals_against"))
    if attack is not None and defence is not None:
        return (_clamp_xg(attack), _clamp_xg(defence), True)

    form = match.signals.home_form if side == "home" else match.signals.away_form
    opponent_form = match.signals.away_form if side == "home" else match.signals.home_form
    attack = 1.18 + (form - 0.5) * 0.70
    defence = 1.18 - (form - 0.5) * 0.45 + (opponent_form - 0.5) * 0.10
    return (_clamp_xg(attack), _clamp_xg(defence), False)


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


def _outcome_probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    outcomes = {"3": 0.0, "1": 0.0, "0": 0.0}
    total = 0.0
    for home_goals in range(MAX_GOALS + 1):
        for away_goals in range(MAX_GOALS + 1):
            probability = _poisson(home_goals, home_xg) * _poisson(away_goals, away_xg)
            probability *= _tau(home_goals, away_goals, home_xg, away_xg)
            total += probability
            if home_goals > away_goals:
                outcomes["3"] += probability
            elif home_goals == away_goals:
                outcomes["1"] += probability
            else:
                outcomes["0"] += probability
    return {outcome: value / total for outcome, value in outcomes.items()} if total else {"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}


def _tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * LOW_SCORE_RHO
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * LOW_SCORE_RHO
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * LOW_SCORE_RHO
    if home_goals == 1 and away_goals == 1:
        return 1.0 - LOW_SCORE_RHO
    return 1.0


def _poisson(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * expected_goals**goals / factorial(goals)


def _number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _clamp_xg(value: float) -> float:
    return min(3.2, max(0.35, value))
