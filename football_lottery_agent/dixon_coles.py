from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, factorial, log
import re

from .models import Match


HOME_ADVANTAGE = 1.08
LOW_SCORE_RHO = -0.08
MAX_GOALS = 7
LEAGUE_RATE_PRIOR = 1.30
XG_PRIOR_WEIGHT = 2.5
GOALS_PRIOR_WEIGHT = 6.0
TIME_DECAY_HALF_LIFE_DAYS = 120.0
MIN_FIT_MATCHES = 8
MIN_TARGET_MATCHES = 3
FIT_ITERATIONS = 360
TEAM_L2 = 2.8
LEAGUE_L2 = 8.0
HOME_ADVANTAGE_L2 = 10.0
GOALS_OBSERVATION_WEIGHT = 0.58
FITTED_MODEL_VERSION = "fitted-dixon-coles-v1"


@dataclass(frozen=True)
class DixonColesForecast:
    home_xg: float
    away_xg: float
    probabilities: dict[str, float]
    data_quality: str
    data_quality_score: float
    model_version: str = "aggregate-poisson-fallback"
    fit_sample_count: int = 0
    effective_sample_count: float = 0.0
    league_goal_rate: float = LEAGUE_RATE_PRIOR
    home_advantage: float = HOME_ADVANTAGE
    rho: float = LOW_SCORE_RHO
    zero_zero_probability: float = 0.0
    one_one_probability: float = 0.0
    low_score_draw_probability: float = 0.0
    league_draw_rate: float = 0.27


@dataclass(frozen=True)
class _TeamRates:
    attack: float
    defence: float
    quality: str
    confidence: float


@dataclass(frozen=True)
class _HistoricalMatch:
    match_id: str
    kickoff: datetime
    league_key: str
    league_name: str
    home_team: str
    away_team: str
    home_goals: float
    away_goals: float
    home_xg: float | None
    away_xg: float | None
    neutral_venue: bool


@dataclass(frozen=True)
class _FittedModel:
    base_log_rate: float
    home_log_advantage: float
    attacks: dict[str, float]
    defences: dict[str, float]
    league_effects: dict[str, float]
    league_home_effects: dict[str, float]
    target_league_key: str
    rho: float
    sample_count: int
    effective_sample_count: float
    home_team_samples: int
    away_team_samples: int
    xg_coverage: float
    league_draw_rate: float


def forecast(match: Match) -> DixonColesForecast:
    """Produce an independent 3/1/0 prior from team attack/defence rates.

    When the full FotMob strength profile is present, recent xG/xGA is used.
    Simple analyses fall back to recent-form signals, keeping the model bounded
    and explicitly lower-confidence rather than silently using bookmaker odds.
    """
    source = match.sources.get("strength_model") if isinstance(match.sources, dict) else {}
    source = source if isinstance(source, dict) else {}
    fitted = _fit_recent_history(match, source)
    if fitted is not None:
        home_key = _team_key(source.get("home_team_id"), source.get("candidate_home") or match.home)
        away_key = _team_key(source.get("away_team_id"), source.get("candidate_away") or match.away)
        league_effect = fitted.league_effects.get(fitted.target_league_key, 0.0)
        neutral = _current_match_is_neutral(match, source)
        home_log_advantage = 0.0 if neutral else (
            fitted.home_log_advantage + fitted.league_home_effects.get(fitted.target_league_key, 0.0)
        )
        home_xg = _clamp_xg(
            exp(
                fitted.base_log_rate
                + league_effect
                + home_log_advantage
                + fitted.attacks.get(home_key, 0.0)
                + fitted.defences.get(away_key, 0.0)
            )
        )
        away_xg = _clamp_xg(
            exp(
                fitted.base_log_rate
                + league_effect
                + fitted.attacks.get(away_key, 0.0)
                + fitted.defences.get(home_key, 0.0)
            )
        )
        home_xg, away_xg = _apply_squad_strength(source, home_xg, away_xg)
        target_samples = min(fitted.home_team_samples, fitted.away_team_samples)
        complete = fitted.sample_count >= 16 and target_samples >= 6
        confidence = min(
            0.86,
            0.46
            + 0.006 * min(fitted.effective_sample_count, 40.0)
            + 0.008 * min(target_samples, 15)
            + 0.08 * fitted.xg_coverage,
        )
        league_rate = exp(fitted.base_log_rate + league_effect)
        home_advantage = 1.0 if neutral else exp(home_log_advantage)
        probabilities, zero_zero, one_one = _probability_summary(home_xg, away_xg, fitted.rho)
        return DixonColesForecast(
            home_xg=home_xg,
            away_xg=away_xg,
            probabilities=probabilities,
            data_quality="fitted" if complete else "partial_fitted",
            data_quality_score=round(confidence, 3),
            model_version=FITTED_MODEL_VERSION,
            fit_sample_count=fitted.sample_count,
            effective_sample_count=round(fitted.effective_sample_count, 2),
            league_goal_rate=round(league_rate, 3),
            home_advantage=round(home_advantage, 3),
            rho=round(fitted.rho, 4),
            zero_zero_probability=round(zero_zero, 6),
            one_one_probability=round(one_one, 6),
            low_score_draw_probability=round(zero_zero + one_one, 6),
            league_draw_rate=round(fitted.league_draw_rate, 4),
        )

    home_rates = _team_rates(source, "home", match)
    away_rates = _team_rates(source, "away", match)
    home_xg = _clamp_xg((home_rates.attack * away_rates.defence) ** 0.5 * HOME_ADVANTAGE)
    away_xg = _clamp_xg((away_rates.attack * home_rates.defence) ** 0.5)

    # Injury and schedule evidence belongs to the information correction layer.
    # Applying it to xG here as well would count the same evidence twice.
    home_xg, away_xg = _apply_squad_strength(source, home_xg, away_xg)
    rho = _draw_rho(source)
    probabilities, zero_zero, one_one = _probability_summary(home_xg, away_xg, rho)
    quality = _combined_quality(home_rates.quality, away_rates.quality)
    quality_score = round((home_rates.confidence + away_rates.confidence) / 2.0, 3)
    return DixonColesForecast(
        home_xg=home_xg,
        away_xg=away_xg,
        probabilities=probabilities,
        data_quality=quality,
        data_quality_score=quality_score,
        rho=rho,
        zero_zero_probability=round(zero_zero, 6),
        one_one_probability=round(one_one, 6),
        low_score_draw_probability=round(zero_zero + one_one, 6),
        league_draw_rate=round(_fallback_draw_rate(source), 4),
    )


def _fit_recent_history(match: Match, source: dict[str, object]) -> _FittedModel | None:
    history = _historical_matches(source, before=match.kickoff)
    if len(history) < MIN_FIT_MATCHES:
        return None

    home_key = _team_key(source.get("home_team_id"), source.get("candidate_home") or match.home)
    away_key = _team_key(source.get("away_team_id"), source.get("candidate_away") or match.away)
    home_samples = sum(home_key in (item.home_team, item.away_team) for item in history)
    away_samples = sum(away_key in (item.home_team, item.away_team) for item in history)
    if min(home_samples, away_samples) < MIN_TARGET_MATCHES:
        return None

    target_league_key = _target_league_key(match, source)
    team_keys = {team for item in history for team in (item.home_team, item.away_team)}
    league_keys = {item.league_key for item in history}
    attacks = {team: 0.0 for team in team_keys}
    defences = {team: 0.0 for team in team_keys}
    league_effects = {league: 0.0 for league in league_keys}
    league_home_effects = {league: 0.0 for league in league_keys}

    prepared: list[tuple[_HistoricalMatch, float, float, float, bool]] = []
    weighted_goals = 0.0
    weighted_sides = 0.0
    xg_weight = 0.0
    total_weight = 0.0
    for item in history:
        base_weight = _history_weight(item, match.kickoff, target_league_key)
        has_xg = item.home_xg is not None and item.away_xg is not None
        observation_weight = base_weight * (1.0 if has_xg else GOALS_OBSERVATION_WEIGHT)
        home_target = item.home_xg if has_xg else item.home_goals
        away_target = item.away_xg if has_xg else item.away_goals
        if home_target is None or away_target is None:
            continue
        prepared.append((item, observation_weight, home_target, away_target, has_xg))
        weighted_goals += observation_weight * (home_target + away_target)
        weighted_sides += 2.0 * observation_weight
        total_weight += base_weight
        if has_xg:
            xg_weight += base_weight
    if len(prepared) < MIN_FIT_MATCHES or weighted_sides <= 0:
        return None

    base_log_rate = log(min(2.2, max(0.75, weighted_goals / weighted_sides)))
    home_log_advantage = log(1.12)
    for iteration in range(FIT_ITERATIONS):
        attack_grad = {team: 0.0 for team in team_keys}
        defence_grad = {team: 0.0 for team in team_keys}
        attack_weight = {team: 0.0 for team in team_keys}
        defence_weight = {team: 0.0 for team in team_keys}
        league_grad = {league: 0.0 for league in league_keys}
        league_weight = {league: 0.0 for league in league_keys}
        league_home_grad = {league: 0.0 for league in league_keys}
        league_home_weight = {league: 0.0 for league in league_keys}
        base_grad = 0.0
        base_weight = 0.0
        home_grad = 0.0
        home_weight = 0.0
        for item, weight, home_target, away_target, _ in prepared:
            league_effect = league_effects[item.league_key]
            venue_effect = 0.0 if item.neutral_venue else (
                home_log_advantage + league_home_effects[item.league_key]
            )
            home_rate = exp(
                base_log_rate
                + league_effect
                + venue_effect
                + attacks[item.home_team]
                + defences[item.away_team]
            )
            away_rate = exp(
                base_log_rate
                + league_effect
                + attacks[item.away_team]
                + defences[item.home_team]
            )
            home_residual = weight * (home_target - home_rate)
            away_residual = weight * (away_target - away_rate)
            base_grad += home_residual + away_residual
            base_weight += 2.0 * weight
            league_grad[item.league_key] += home_residual + away_residual
            league_weight[item.league_key] += 2.0 * weight
            attack_grad[item.home_team] += home_residual
            attack_grad[item.away_team] += away_residual
            attack_weight[item.home_team] += weight
            attack_weight[item.away_team] += weight
            defence_grad[item.away_team] += home_residual
            defence_grad[item.home_team] += away_residual
            defence_weight[item.away_team] += weight
            defence_weight[item.home_team] += weight
            if not item.neutral_venue:
                home_grad += home_residual
                home_weight += weight
                league_home_grad[item.league_key] += home_residual
                league_home_weight[item.league_key] += weight

        progress = iteration / max(FIT_ITERATIONS - 1, 1)
        learning_rate = 0.075 * (1.0 - 0.65 * progress)
        base_log_rate = _clamp(
            base_log_rate + learning_rate * base_grad / max(base_weight, 1.0),
            log(0.65),
            log(2.35),
        )
        home_log_advantage = _clamp(
            home_log_advantage
            + learning_rate
            * (home_grad - HOME_ADVANTAGE_L2 * home_log_advantage)
            / max(home_weight + HOME_ADVANTAGE_L2, 1.0),
            log(0.82),
            log(1.55),
        )
        for team in team_keys:
            attacks[team] = _clamp(
                attacks[team]
                + learning_rate
                * (attack_grad[team] - TEAM_L2 * attacks[team])
                / max(attack_weight[team] + TEAM_L2, 1.0),
                -0.85,
                0.85,
            )
            defences[team] = _clamp(
                defences[team]
                + learning_rate
                * (defence_grad[team] - TEAM_L2 * defences[team])
                / max(defence_weight[team] + TEAM_L2, 1.0),
                -0.85,
                0.85,
            )
        for league in league_keys:
            league_effects[league] = _clamp(
                league_effects[league]
                + learning_rate
                * (league_grad[league] - LEAGUE_L2 * league_effects[league])
                / max(league_weight[league] + LEAGUE_L2, 1.0),
                -0.32,
                0.32,
            )
            league_home_effects[league] = _clamp(
                league_home_effects[league]
                + learning_rate
                * (league_home_grad[league] - LEAGUE_L2 * league_home_effects[league])
                / max(league_home_weight[league] + LEAGUE_L2, 1.0),
                -0.20,
                0.20,
            )

    rho = _fit_rho(
        history,
        match.kickoff,
        target_league_key,
        base_log_rate,
        home_log_advantage,
        attacks,
        defences,
        league_effects,
        league_home_effects,
    )
    effective_sample_count = sum(_history_weight(item, match.kickoff, target_league_key) for item in history)
    league_draw_rate = _fitted_league_draw_rate(history, match.kickoff, target_league_key)
    return _FittedModel(
        base_log_rate=base_log_rate,
        home_log_advantage=home_log_advantage,
        attacks=attacks,
        defences=defences,
        league_effects=league_effects,
        league_home_effects=league_home_effects,
        target_league_key=target_league_key,
        rho=rho,
        sample_count=len(history),
        effective_sample_count=effective_sample_count,
        home_team_samples=home_samples,
        away_team_samples=away_samples,
        xg_coverage=xg_weight / total_weight if total_weight else 0.0,
        league_draw_rate=league_draw_rate,
    )


def _historical_matches(source: dict[str, object], *, before: datetime) -> list[_HistoricalMatch]:
    by_match: dict[str, _HistoricalMatch] = {}
    for field in ("home_recent_matches", "away_recent_matches", "league_recent_matches"):
        rows = source.get(field)
        if not isinstance(rows, list):
            continue
        for raw in rows:
            item = _parse_historical_match(raw, before=before)
            if item is None:
                continue
            key = item.match_id or (
                f"{item.kickoff.isoformat()}|{item.home_team}|{item.away_team}"
            )
            previous = by_match.get(key)
            if previous is None or (
                previous.home_xg is None
                and item.home_xg is not None
                and item.away_xg is not None
            ):
                by_match[key] = item
    return sorted(by_match.values(), key=lambda item: item.kickoff, reverse=True)


def _parse_historical_match(raw: object, *, before: datetime) -> _HistoricalMatch | None:
    if not isinstance(raw, dict):
        return None
    kickoff = _datetime(raw.get("kickoff"))
    if kickoff is None or not _is_before(kickoff, before):
        return None
    home_goals = _nonnegative_number(raw.get("home_goals"))
    away_goals = _nonnegative_number(raw.get("away_goals"))
    if home_goals is None or away_goals is None:
        return None
    home_team = _team_key(raw.get("home_team_id"), raw.get("home_team"))
    away_team = _team_key(raw.get("away_team_id"), raw.get("away_team"))
    if not home_team or not away_team or home_team == away_team:
        return None
    return _HistoricalMatch(
        match_id=str(raw.get("match_id") or "").strip(),
        kickoff=kickoff,
        league_key=_league_key(raw.get("league_id"), raw.get("league")),
        league_name=str(raw.get("league") or "").strip(),
        home_team=home_team,
        away_team=away_team,
        home_goals=home_goals,
        away_goals=away_goals,
        home_xg=_nonnegative_number(raw.get("home_xg")),
        away_xg=_nonnegative_number(raw.get("away_xg")),
        neutral_venue=_truthy(raw.get("neutral_venue")),
    )


def _fit_rho(
    history: list[_HistoricalMatch],
    target_time: datetime,
    target_league_key: str,
    base_log_rate: float,
    home_log_advantage: float,
    attacks: dict[str, float],
    defences: dict[str, float],
    league_effects: dict[str, float],
    league_home_effects: dict[str, float],
) -> float:
    best_rho = LOW_SCORE_RHO
    best_score = float("-inf")
    for step in range(-18, 9):
        rho = step / 100.0
        score = -5.0 * (rho - LOW_SCORE_RHO) ** 2
        valid = True
        for item in history:
            league_effect = league_effects.get(item.league_key, 0.0)
            venue_effect = 0.0 if item.neutral_venue else (
                home_log_advantage + league_home_effects.get(item.league_key, 0.0)
            )
            home_rate = exp(
                base_log_rate
                + league_effect
                + venue_effect
                + attacks.get(item.home_team, 0.0)
                + defences.get(item.away_team, 0.0)
            )
            away_rate = exp(
                base_log_rate
                + league_effect
                + attacks.get(item.away_team, 0.0)
                + defences.get(item.home_team, 0.0)
            )
            tau = _tau(int(item.home_goals), int(item.away_goals), home_rate, away_rate, rho)
            if tau <= 0:
                valid = False
                break
            score += _history_weight(item, target_time, target_league_key) * log(tau)
        if valid and score > best_score:
            best_score = score
            best_rho = rho
    effective = sum(_history_weight(item, target_time, target_league_key) for item in history)
    prior_matches = 16.0
    return (best_rho * effective + LOW_SCORE_RHO * prior_matches) / (effective + prior_matches)


def _history_weight(item: _HistoricalMatch, target_time: datetime, target_league_key: str) -> float:
    days = max(0.0, _elapsed_days(item.kickoff, target_time))
    time_weight = 0.5 ** (days / TIME_DECAY_HALF_LIFE_DAYS)
    competition_weight = 1.0 if item.league_key == target_league_key else 0.72
    normalized_league = _normalize_name(item.league_name)
    if "friendly" in normalized_league or "友谊" in item.league_name:
        competition_weight *= 0.45
    return time_weight * competition_weight


def _target_league_key(match: Match, source: dict[str, object]) -> str:
    return _league_key(
        source.get("candidate_league_id"),
        source.get("candidate_league") or match.league,
    )


def _league_key(identifier: object, name: object) -> str:
    try:
        numeric = int(identifier or 0)
    except (TypeError, ValueError):
        numeric = 0
    if numeric:
        return f"id:{numeric}"
    normalized = _normalize_name(str(name or ""))
    return f"name:{normalized or 'unknown'}"


def _team_key(identifier: object, name: object) -> str:
    try:
        numeric = int(identifier or 0)
    except (TypeError, ValueError):
        numeric = 0
    if numeric:
        return f"id:{numeric}"
    normalized = _normalize_name(str(name or ""))
    return f"name:{normalized}" if normalized else ""


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.casefold()).strip()


def _datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_before(first: datetime, second: datetime) -> bool:
    return _as_utc(first) < _as_utc(second)


def _elapsed_days(first: datetime, second: datetime) -> float:
    return (_as_utc(second) - _as_utc(first)).total_seconds() / 86400.0


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _current_match_is_neutral(match: Match, source: dict[str, object]) -> bool:
    if _truthy(source.get("neutral_venue")):
        return True
    return _truthy(match.sources.get("neutral_venue")) if isinstance(match.sources, dict) else False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"true", "yes", "1"}


def _nonnegative_number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= 0 else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


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
    """Apply only pre-availability paper strength to the xG prior.

    Current-XI ratings and availability penalties already encode absences, so
    using either here would duplicate the information-layer injury correction.
    """
    home_rating = _number(source.get("home_squad_paper_rating"))
    away_rating = _number(source.get("away_squad_paper_rating"))
    if home_rating is None or away_rating is None:
        return home_xg, away_xg
    edge = max(-0.16, min(0.16, log(home_rating / away_rating) * 0.12))
    home_factor = 1.0 + edge
    away_factor = 1.0 - edge
    return _clamp_xg(home_xg * home_factor), _clamp_xg(away_xg * away_factor)


def _outcome_probabilities(
    home_xg: float,
    away_xg: float,
    rho: float = LOW_SCORE_RHO,
) -> dict[str, float]:
    return _probability_summary(home_xg, away_xg, rho)[0]


def _probability_summary(
    home_xg: float,
    away_xg: float,
    rho: float = LOW_SCORE_RHO,
) -> tuple[dict[str, float], float, float]:
    outcomes = {"3": 0.0, "1": 0.0, "0": 0.0}
    total = 0.0
    zero_zero = 0.0
    one_one = 0.0
    for home_goals in range(MAX_GOALS + 1):
        for away_goals in range(MAX_GOALS + 1):
            probability = _poisson(home_goals, home_xg) * _poisson(away_goals, away_xg)
            probability *= _tau(home_goals, away_goals, home_xg, away_xg, rho)
            total += probability
            if home_goals == 0 and away_goals == 0:
                zero_zero = probability
            elif home_goals == 1 and away_goals == 1:
                one_one = probability
            if home_goals > away_goals:
                outcomes["3"] += probability
            elif home_goals == away_goals:
                outcomes["1"] += probability
            else:
                outcomes["0"] += probability
    if not total:
        return {"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}, 0.0, 0.0
    return (
        {outcome: value / total for outcome, value in outcomes.items()},
        zero_zero / total,
        one_one / total,
    )


def _fitted_league_draw_rate(
    history: list[_HistoricalMatch],
    target_time: datetime,
    target_league_key: str,
) -> float:
    weighted_draws = 0.0
    total_weight = 0.0
    for item in history:
        if item.league_key != target_league_key:
            continue
        weight = _history_weight(item, target_time, target_league_key)
        total_weight += weight
        weighted_draws += weight * float(item.home_goals == item.away_goals)
    prior_matches = 12.0
    return (weighted_draws + 0.27 * prior_matches) / (total_weight + prior_matches)


def _fallback_draw_rate(source: dict[str, object]) -> float:
    rates = [
        value
        for value in (
            _probability(source.get("home_draw_rate")),
            _probability(source.get("away_draw_rate")),
        )
        if value is not None
    ]
    if not rates:
        return 0.27
    samples = min(
        20.0,
        float(_sample_count(source.get("home_matches_used"), default=6))
        + float(_sample_count(source.get("away_matches_used"), default=6)),
    )
    observed = sum(rates) / len(rates)
    return (observed * samples + 0.27 * 10.0) / (samples + 10.0)


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
