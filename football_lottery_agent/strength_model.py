from __future__ import annotations

import csv
import hashlib
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from .bilingual_identity import fetch_dbpedia_club_aliases
from .collectors import RawMatch
from .http_utils import read_url_text
from .json_utils import loads_json
from .team_identity import (
    TEAM_ALIASES,
    configure_team_identity,
    identity_path_for_cache,
    normalize_team_name,
    provider_team_match_score,
    register_team_alias,
    team_match_score,
)


FOTMOB_BASE = "https://www.fotmob.com/api/data"
_JSON_OBJECT_CACHE_LIMIT = 64
_JSON_OBJECT_CACHE: OrderedDict[str, tuple[int, int, Any]] = OrderedDict()
_JSON_OBJECT_CACHE_LOCK = RLock()
FOTMOB_LEAGUE_ALIASES: dict[str, tuple[str, ...]] = {
    "英超": ("premier league",),
    "英冠": ("championship",),
    "英甲": ("league one",),
    "英乙": ("league two",),
    "英联赛杯": ("efl cup", "league cup"),
    "英足总杯": ("fa cup",),
    "西甲": ("laliga", "la liga"),
    "西乙": ("laliga 2", "la liga 2", "segunda division"),
    "德甲": ("bundesliga",),
    "德乙": ("2. bundesliga",),
    "意甲": ("serie a",),
    "意乙": ("serie b",),
    "法甲": ("ligue 1",),
    "法乙": ("ligue 2",),
    "荷甲": ("eredivisie",),
    "荷乙": ("eerste divisie",),
    "葡超": ("liga portugal", "primeira liga"),
    "苏超": ("premiership", "scottish premiership"),
    "比甲": ("pro league", "first division a"),
    "瑞超": ("allsvenskan",),
    "挪超": ("eliteserien",),
    "芬超": ("veikkausliiga",),
    "丹超": ("superliga",),
    "欧冠": ("champions league", "champions league qualification"),
    "欧联": ("europa league", "europa league qualification"),
    "欧罗巴": ("europa league", "europa league qualification"),
    "世界杯": ("world cup",),
    "日职": ("j league", "j. league"),
    "韩职": ("k league 1",),
    "美职": ("major league soccer", "mls"),
}

@dataclass(frozen=True)
class TeamRef:
    id: int
    name: str


@dataclass(frozen=True)
class MatchStat:
    match_id: int
    date: str
    is_home: bool
    goals_for: int
    goals_against: int
    result: str
    opponent: str


@dataclass(frozen=True)
class StrengthProfile:
    team: TeamRef
    matches_used: int
    win_rate: float
    draw_rate: float
    loss_rate: float
    home_win_rate: float | None
    away_win_rate: float | None
    home_matches_used: int
    away_matches_used: int
    goals_for_per_match: float
    goals_against_per_match: float
    xg_for_per_match: float | None
    xg_against_per_match: float | None
    rating: float
    notes: tuple[str, ...]
    xg_matches_used: int = 0
    xg_provider: str = ""


@dataclass(frozen=True)
class SquadProfile:
    """A pre-match paper-strength view built only from the current team roster."""

    team: TeamRef
    players_count: int
    estimated_starting_value: float
    paper_rating: float
    current_rating: float
    attack_rating: float
    defence_rating: float
    recent_form_rating: float | None
    recent_form_samples: int
    unavailable_count: int
    unavailable_value: float
    availability_penalty: float
    notable_absences: tuple[str, ...]


@dataclass(frozen=True)
class FixtureStrength:
    home: StrengthProfile | None
    away: StrengthProfile | None
    home_squad: SquadProfile | None
    away_squad: SquadProfile | None
    h2h: tuple[str, ...]
    source: dict[str, Any]


def build_strength_for_matches(
    matches: list[RawMatch],
    cache_dir: str | Path,
    team_ids_path: str | Path | None = None,
    lookback: int = 20,
    xg_matches: int = 8,
) -> dict[int, FixtureStrength]:
    configure_team_identity(identity_path_for_cache(cache_dir))
    cache = Path(cache_dir) / "fotmob"
    id_overrides = load_team_ids(team_ids_path) if team_ids_path else {}
    fotmob_events = _fetch_events_for_dates(matches, cache)
    _learn_unique_context_provider_aliases(matches, fotmob_events)
    _learn_one_sided_provider_aliases(matches, fotmob_events)
    _learn_bilingual_provider_aliases(matches, fotmob_events, Path(cache_dir))

    result: dict[int, FixtureStrength] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_build_fixture_strength, match, cache, id_overrides, fotmob_events, lookback, xg_matches)
            for match in matches
        ]
        for match, future in zip(matches, futures):
            result[match.seq] = future.result()

    # SofaScore is an additive source: it fills missing team/xG history but
    # never removes FotMob lineup, squad or form information.
    from .sofascore import build_sofascore_for_matches

    sofascore = build_sofascore_for_matches(
        matches,
        cache_dir=cache_dir,
        lookback=lookback,
        xg_matches=xg_matches,
        team_score=_team_score,
    )
    for match in matches:
        result[match.seq] = _merge_sofascore_strength(result.get(match.seq), sofascore.get(match.seq))
    return result


def load_team_ids(path: str | Path) -> dict[str, int]:
    if not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return {row["name"].strip(): int(row["fotmob_id"]) for row in rows if row.get("name") and row.get("fotmob_id")}


def _build_fixture_strength(
    match: RawMatch,
    cache: Path,
    id_overrides: dict[str, int],
    fotmob_events: dict[str, list[dict[str, Any]]],
    lookback: int,
    xg_matches: int,
) -> FixtureStrength:
    event, reversed_sides, match_diagnostic = _match_fotmob_event(match, fotmob_events)
    home_side = "away" if reversed_sides else "home"
    away_side = "home" if reversed_sides else "away"
    if event:
        _remember_fotmob_side(match.home, event.get(home_side) or {}, match_diagnostic)
        _remember_fotmob_side(match.away, event.get(away_side) or {}, match_diagnostic)
    home_ref = _team_ref(match.home, home_side, event, id_overrides)
    away_ref = _team_ref(match.away, away_side, event, id_overrides)

    # A FotMob matchDetails payload is large. The former path parsed each
    # recent game once for xG and again for player form, and parsed the current
    # fixture once for absences and again for H2H. Keep one fixture-local map
    # so every payload is fetched and decoded only once per analysis.
    match_details: dict[int, Any] = {}
    # An empty mapping is also a completed fetch result.  Passing it through
    # prevents the profile and squad paths from retrying the same failed team
    # request independently.
    home_team_data = (_fetch_team_data(home_ref, cache) or {}) if home_ref else None
    away_team_data = (_fetch_team_data(away_ref, cache) or {}) if away_ref else None
    home = (
        _build_team_profile(home_ref, cache, lookback, xg_matches, home_team_data, match_details)
        if home_ref
        else None
    )
    away = (
        _build_team_profile(away_ref, cache, lookback, xg_matches, away_team_data, match_details)
        if away_ref
        else None
    )
    unavailable = _fixture_unavailable(event, cache, match_details)
    home_squad = (
        _build_squad_profile(home_ref, cache, unavailable.get("home", ()), home_team_data, match_details)
        if home_ref
        else None
    )
    away_squad = (
        _build_squad_profile(away_ref, cache, unavailable.get("away", ()), away_team_data, match_details)
        if away_ref
        else None
    )
    h2h = _extract_h2h_from_event(event, cache, match_details) if event else ()
    return FixtureStrength(
        home=home,
        away=away,
        home_squad=home_squad,
        away_squad=away_squad,
        h2h=h2h,
        source={
            "provider": "fotmob",
            "matched_event_id": event.get("id") if event else "",
            "home_team_id": home_ref.id if home_ref else "",
            "away_team_id": away_ref.id if away_ref else "",
            "lookback": lookback,
            "xg_matches": xg_matches,
            **match_diagnostic,
        },
    )


def _fetch_team_data(team: TeamRef, cache: Path) -> dict[str, Any] | None:
    payload = _fetch_json(f"{FOTMOB_BASE}/teams?{urllib.parse.urlencode({'id': team.id})}", cache, 86400)
    return payload if isinstance(payload, dict) else None


def _build_team_profile(
    team: TeamRef,
    cache: Path,
    lookback: int,
    xg_matches: int,
    team_data: dict[str, Any] | None = None,
    match_details: dict[int, Any] | None = None,
) -> StrengthProfile | None:
    if team_data is None:
        team_data = _fetch_team_data(team, cache)
    fixtures = (((team_data or {}).get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or []
    finished = [_fixture_to_match_stat(item, team.id) for item in fixtures if _is_finished(item)]
    finished = [item for item in finished if item is not None]
    finished.sort(key=lambda item: item.date, reverse=True)
    recent = finished[:lookback]
    if not recent:
        return None

    xg_for = []
    xg_against = []
    for item in recent[:xg_matches]:
        xg = _fetch_match_xg(item.match_id, team.id, cache, match_details)
        if xg:
            xg_for.append(xg[0])
            xg_against.append(xg[1])

    wins = sum(1 for item in recent if item.result == "W")
    draws = sum(1 for item in recent if item.result == "D")
    losses = sum(1 for item in recent if item.result == "L")
    home_games = [item for item in recent if item.is_home]
    away_games = [item for item in recent if not item.is_home]
    gf = sum(item.goals_for for item in recent) / len(recent)
    ga = sum(item.goals_against for item in recent) / len(recent)
    xgf = sum(xg_for) / len(xg_for) if xg_for else None
    xga = sum(xg_against) / len(xg_against) if xg_against else None
    rating = _rating(wins / len(recent), draws / len(recent), gf, ga, xgf, xga)

    notes = (
        f"{team.name} 近{len(recent)}场 {wins}胜{draws}平{losses}负，场均进{gf:.2f}/失{ga:.2f}。",
        f"主场胜率 {_rate_text(home_games)}，客场胜率 {_rate_text(away_games)}。",
        f"xG样本 {len(xg_for)} 场：{_nullable(xgf)} / {_nullable(xga)}。",
    )
    return StrengthProfile(
        team=team,
        matches_used=len(recent),
        win_rate=round(wins / len(recent), 3),
        draw_rate=round(draws / len(recent), 3),
        loss_rate=round(losses / len(recent), 3),
        home_win_rate=_win_rate(home_games),
        away_win_rate=_win_rate(away_games),
        home_matches_used=len(home_games),
        away_matches_used=len(away_games),
        goals_for_per_match=round(gf, 3),
        goals_against_per_match=round(ga, 3),
        xg_for_per_match=round(xgf, 3) if xgf is not None else None,
        xg_against_per_match=round(xga, 3) if xga is not None else None,
        rating=round(rating, 3),
        notes=notes,
        xg_matches_used=len(xg_for),
        xg_provider="fotmob" if xg_for else "",
    )


def _merge_sofascore_strength(primary: FixtureStrength | None, sofascore: Any) -> FixtureStrength:
    if primary is None:
        primary = FixtureStrength(home=None, away=None, home_squad=None, away_squad=None, h2h=(), source={})
    if not sofascore:
        return primary

    home = _merge_sofascore_profile(primary.home, getattr(sofascore, "home", None))
    away = _merge_sofascore_profile(primary.away, getattr(sofascore, "away", None))
    sofa_source = dict(getattr(sofascore, "source", {}) or {})
    has_sofa_data = bool(getattr(sofascore, "home", None) or getattr(sofascore, "away", None))
    provider = str(primary.source.get("provider") or "")
    if has_sofa_data:
        provider = f"{provider}+sofascore".strip("+")
    return FixtureStrength(
        home=home,
        away=away,
        home_squad=primary.home_squad,
        away_squad=primary.away_squad,
        h2h=primary.h2h,
        source={**primary.source, "provider": provider or "sofascore", "sofascore": sofa_source},
    )


def _merge_sofascore_profile(primary: StrengthProfile | None, sofascore: Any) -> StrengthProfile | None:
    if sofascore is None:
        return primary
    if primary is None:
        rating = _rating(
            sofascore.win_rate,
            sofascore.draw_rate,
            sofascore.goals_for_per_match,
            sofascore.goals_against_per_match,
            sofascore.xg_for_per_match,
            sofascore.xg_against_per_match,
        )
        return StrengthProfile(
            team=TeamRef(sofascore.team_id, sofascore.team_name),
            matches_used=sofascore.matches_used,
            win_rate=sofascore.win_rate,
            draw_rate=sofascore.draw_rate,
            loss_rate=sofascore.loss_rate,
            home_win_rate=sofascore.home_win_rate,
            away_win_rate=sofascore.away_win_rate,
            home_matches_used=sofascore.home_matches_used,
            away_matches_used=sofascore.away_matches_used,
            goals_for_per_match=sofascore.goals_for_per_match,
            goals_against_per_match=sofascore.goals_against_per_match,
            xg_for_per_match=sofascore.xg_for_per_match,
            xg_against_per_match=sofascore.xg_against_per_match,
            rating=round(rating, 3),
            notes=sofascore.notes,
            xg_matches_used=sofascore.xg_matches_used,
            xg_provider="sofascore" if sofascore.xg_matches_used else "",
        )

    primary_has_xg = primary.xg_for_per_match is not None and primary.xg_against_per_match is not None
    sofa_has_xg = sofascore.xg_for_per_match is not None and sofascore.xg_against_per_match is not None
    use_sofascore_xg = sofa_has_xg and (
        not primary_has_xg or sofascore.xg_matches_used > max(3, primary.xg_matches_used)
    )
    xgf = sofascore.xg_for_per_match if use_sofascore_xg else primary.xg_for_per_match
    xga = sofascore.xg_against_per_match if use_sofascore_xg else primary.xg_against_per_match
    xg_matches = sofascore.xg_matches_used if use_sofascore_xg else primary.xg_matches_used
    xg_provider = "sofascore" if use_sofascore_xg else primary.xg_provider
    notes = tuple(dict.fromkeys((*primary.notes, *sofascore.notes)))
    rating = _rating(
        primary.win_rate,
        primary.draw_rate,
        primary.goals_for_per_match,
        primary.goals_against_per_match,
        xgf,
        xga,
    )
    return StrengthProfile(
        team=primary.team,
        matches_used=primary.matches_used,
        win_rate=primary.win_rate,
        draw_rate=primary.draw_rate,
        loss_rate=primary.loss_rate,
        home_win_rate=primary.home_win_rate,
        away_win_rate=primary.away_win_rate,
        home_matches_used=primary.home_matches_used,
        away_matches_used=primary.away_matches_used,
        goals_for_per_match=primary.goals_for_per_match,
        goals_against_per_match=primary.goals_against_per_match,
        xg_for_per_match=xgf,
        xg_against_per_match=xga,
        rating=round(rating, 3),
        notes=notes,
        xg_matches_used=xg_matches,
        xg_provider=xg_provider,
    )


def _build_squad_profile(
    team: TeamRef,
    cache: Path,
    fixture_unavailable: tuple[dict[str, Any], ...],
    team_data: dict[str, Any] | None = None,
    match_details: dict[int, Any] | None = None,
) -> SquadProfile | None:
    if team_data is None:
        team_data = _fetch_team_data(team, cache)
    groups = (((team_data or {}).get("squad") or {}).get("squad")) or []
    players = [member for group in groups for member in (group.get("members") or []) if _is_player(member)]
    if len(players) < 11:
        return None

    unavailable_ids = {str(item.get("id")) for item in fixture_unavailable if item.get("id") is not None}
    unavailable_ids.update(str(player.get("id")) for player in players if _has_injury(player.get("injury")))
    unavailable_players = [player for player in players if str(player.get("id")) in unavailable_ids]
    available_players = [player for player in players if str(player.get("id")) not in unavailable_ids]
    recent_forms = _recent_player_forms(team, team_data or {}, cache, match_details=match_details)
    selected = _estimate_starting_eleven(available_players, recent_forms)
    if len(selected) < 8:
        selected = _estimate_starting_eleven(players, recent_forms)

    starter_value = sum(_player_value(player) for player in selected)
    unavailable_value = sum(_player_value(player) for player in unavailable_players)
    paper_strength = sum(_player_strength(player) for player in selected)
    current_strength = sum(_player_strength(player, recent_forms) for player in selected)
    attack_strength = sum(_player_strength(player, recent_forms) for player in selected if _position_group(player) in {"midfield", "attack"})
    defence_strength = sum(_player_strength(player, recent_forms) for player in selected if _position_group(player) in {"keeper", "defence", "midfield"})
    form_values = [recent_forms[str(player.get("id"))] for player in selected if str(player.get("id")) in recent_forms]
    sample_count = sum(item[0] for item in form_values)
    recent_form = sum(item[0] * item[1] for item in form_values) / sample_count if sample_count else None
    reference_value = max(starter_value + unavailable_value, 1.0)
    penalty = min(0.35, unavailable_value / reference_value)
    absences = tuple(str(player.get("name", "")) for player in sorted(unavailable_players, key=_player_value, reverse=True)[:3] if player.get("name"))
    return SquadProfile(
        team=team,
        players_count=len(players),
        estimated_starting_value=round(starter_value, 1),
        paper_rating=round(paper_strength, 3),
        current_rating=round(current_strength, 3),
        attack_rating=round(attack_strength, 3),
        defence_rating=round(defence_strength, 3),
        recent_form_rating=round(recent_form, 2) if recent_form is not None else None,
        recent_form_samples=sample_count,
        unavailable_count=len(unavailable_players),
        unavailable_value=round(unavailable_value, 1),
        availability_penalty=round(penalty, 3),
        notable_absences=absences,
    )


def _fixture_unavailable(
    event: dict[str, Any] | None,
    cache: Path,
    match_details: dict[int, Any] | None = None,
) -> dict[str, tuple[dict[str, Any], ...]]:
    if not event or _is_finished(event) or not event.get("id"):
        return {"home": (), "away": ()}
    payload = _match_details_payload(int(event["id"]), cache, 900, match_details)
    lineup = (((payload or {}).get("content") or {}).get("lineup")) or {}
    return {
        "home": tuple(((lineup.get("homeTeam") or {}).get("unavailable")) or []),
        "away": tuple(((lineup.get("awayTeam") or {}).get("unavailable")) or []),
    }


def _is_player(member: dict[str, Any]) -> bool:
    return bool(member.get("id")) and _position_group(member) != "other"


def _has_injury(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "null", "false", "0"}
    if isinstance(value, dict):
        return any(_has_injury(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_injury(item) for item in value)
    return bool(value)


def _position_group(player: dict[str, Any]) -> str:
    role = str(((player.get("role") or {}).get("key")) or "").lower()
    position = player.get("positionId")
    if "keeper" in role or position == 0:
        return "keeper"
    if "defender" in role or position == 1:
        return "defence"
    if "midfielder" in role or position == 2:
        return "midfield"
    if "attacker" in role or position == 3:
        return "attack"
    return "other"


def _recent_player_forms(
    team: TeamRef,
    team_data: dict[str, Any],
    cache: Path,
    limit: int = 8,
    match_details: dict[int, Any] | None = None,
) -> dict[str, tuple[int, float]]:
    fixtures = (((team_data.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures")) or []
    finished = [_fixture_to_match_stat(item, team.id) for item in fixtures if _is_finished(item)]
    recent = sorted((item for item in finished if item is not None), key=lambda item: item.date, reverse=True)[:limit]
    values: dict[str, list[float]] = {}
    for item in recent:
        payload = _match_details_payload(item.match_id, cache, 86400 * 30, match_details)
        lineup = (((payload or {}).get("content") or {}).get("lineup")) or {}
        for side in ("homeTeam", "awayTeam"):
            team_lineup = lineup.get(side) or {}
            if int(team_lineup.get("id", -1)) != team.id:
                continue
            for player in list(team_lineup.get("starters") or []) + list(team_lineup.get("subs") or []):
                rating = ((player.get("performance") or {}).get("rating"))
                try:
                    rating = min(8.8, max(5.0, float(rating)))
                except (TypeError, ValueError):
                    continue
                values.setdefault(str(player.get("id")), []).append(rating)
    return {
        player_id: (len(ratings), round(_weighted_recent_average(ratings), 3))
        for player_id, ratings in values.items()
    }


def _weighted_recent_average(ratings: list[float]) -> float:
    weights = [0.88**index for index in range(len(ratings))]
    return sum(rating * weight for rating, weight in zip(ratings, weights)) / sum(weights)


def _estimate_starting_eleven(
    players: list[dict[str, Any]], recent_forms: dict[str, tuple[int, float]] | None = None
) -> list[dict[str, Any]]:
    quotas = (("keeper", 1), ("defence", 4), ("midfield", 3), ("attack", 3))
    selected: list[dict[str, Any]] = []
    for group, quota in quotas:
        candidates = sorted(
            (player for player in players if _position_group(player) == group),
            key=lambda player: _player_strength(player, recent_forms),
            reverse=True,
        )
        selected.extend(candidates[:quota])
    if len(selected) < 11:
        chosen = {str(player.get("id")) for player in selected}
        remaining = sorted(
            (player for player in players if str(player.get("id")) not in chosen),
            key=lambda player: _player_strength(player, recent_forms),
            reverse=True,
        )
        selected.extend(remaining[: 11 - len(selected)])
    return selected[:11]


def _player_value(player: dict[str, Any]) -> float:
    try:
        return max(0.0, float(player.get("transferValue") or player.get("marketValue") or 0.0) / 1_000_000)
    except (TypeError, ValueError):
        return 0.0


def _player_strength(player: dict[str, Any], recent_forms: dict[str, tuple[int, float]] | None = None) -> float:
    weights = {"keeper": 0.9, "defence": 0.95, "midfield": 1.0, "attack": 1.08}
    rating = player.get("rating")
    try:
        base_rating = float(rating)
    except (TypeError, ValueError):
        base_rating = 6.8
    recent = (recent_forms or {}).get(str(player.get("id")))
    if recent:
        appearances, recent_rating = recent
        recent_weight = min(0.45, appearances * 0.12)
        base_rating = base_rating * (1.0 - recent_weight) + recent_rating * recent_weight
    form_factor = min(1.12, max(0.88, 1.0 + (base_rating - 6.8) * 0.04))
    return math.log1p(_player_value(player)) * weights.get(_position_group(player), 1.0) * form_factor


def _fetch_events_for_dates(matches: list[RawMatch], cache: Path) -> dict[str, list[dict[str, Any]]]:
    dates = sorted({date for match in matches for date in _candidate_date_keys(match.kickoff)})
    result = {}
    for date in dates:
        payload = _fetch_json(f"{FOTMOB_BASE}/matches?{urllib.parse.urlencode({'date': date})}", cache, 3600)
        events = []
        for league in (payload or {}).get("leagues", []):
            for item in league.get("matches", []):
                event = dict(item)
                event["_provider_league_name"] = str(league.get("name") or "")
                event["_provider_league_id"] = league.get("id") or ""
                events.append(event)
        result[date] = events
    return result


def _match_fotmob_event(
    match: RawMatch,
    events_by_date: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, bool, dict[str, Any]]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    best_rank = 0.0
    best_reversed = False
    events = _fotmob_events_for_match(match, events_by_date)
    for event in events:
        home = event.get("home") or {}
        away = event.get("away") or {}
        direct = _fotmob_side_score(match.home, home) + _fotmob_side_score(match.away, away)
        reverse = _fotmob_side_score(match.home, away) + _fotmob_side_score(match.away, home) - 0.3
        score = max(direct, reverse)
        distance = _fotmob_kickoff_distance_hours(match, event)
        context_bonus = 0.1 if distance is not None and distance <= 2.0 else 0.0
        rank = score + context_bonus
        if rank > best_rank:
            best_rank = rank
            best_score = score
            best = event
            best_reversed = reverse > direct

    context_candidates = []
    for event in events:
        distance = _fotmob_kickoff_distance_hours(match, event)
        if distance is None or distance > 0.25:
            continue
        context_candidates.append(
            {
                "event_id": event.get("id", ""),
                "home": str((event.get("home") or {}).get("name") or ""),
                "away": str((event.get("away") or {}).get("name") or ""),
                "league": str(event.get("_provider_league_name") or ""),
                "kickoff": str((event.get("status") or {}).get("utcTime") or ""),
            }
        )

    candidate_home = str(((best or {}).get("home") or {}).get("name") or "")
    candidate_away = str(((best or {}).get("away") or {}).get("name") or "")
    matched = best is not None and best_score >= 1.6
    if matched:
        match_reason = "provider_id_or_alias_pair"
    elif len(context_candidates) > 1:
        match_reason = "ambiguous_context_missing_aliases"
    elif len(context_candidates) == 1:
        match_reason = "unique_context_not_learned"
    elif best:
        match_reason = "no_fixture_at_kickoff"
    else:
        match_reason = "no_candidates"
    diagnostic = {
        "match_status": "matched" if matched else "unmatched",
        "match_confidence": round(max(0.0, min(1.0, best_score / 2.0)), 3),
        "match_reason": match_reason,
        "candidate_count": len(context_candidates),
        "candidate_matches": context_candidates[:8],
        "candidate_event_id": (best or {}).get("id", ""),
        "candidate_home": candidate_home,
        "candidate_away": candidate_away,
        "candidate_league": str((best or {}).get("_provider_league_name") or ""),
    }
    return (best, best_reversed, diagnostic) if matched else (None, False, diagnostic)


def _learn_unique_context_provider_aliases(
    matches: list[RawMatch],
    events_by_date: dict[str, list[dict[str, Any]]],
) -> None:
    """Bootstrap two unknown names from a unique competition and kickoff.

    A provider fixture is accepted only when it is the sole event in the
    mapped competition within 15 minutes and belongs to only one local match.
    This deliberately leaves same-time groups unresolved instead of guessing.
    """
    candidates_by_seq: dict[int, list[dict[str, Any]]] = {}
    owners: dict[str, set[int]] = {}
    for match in matches:
        candidates = [
            event
            for event in _fotmob_events_for_match(match, events_by_date)
            if (distance := _fotmob_kickoff_distance_hours(match, event)) is not None and distance <= 0.25
        ]
        candidates_by_seq[match.seq] = candidates
        for event in candidates:
            owners.setdefault(_fotmob_event_key(event), set()).add(match.seq)

    for match in matches:
        candidates = candidates_by_seq.get(match.seq, ())
        if len(candidates) != 1:
            continue
        event = candidates[0]
        if len(owners.get(_fotmob_event_key(event), ())) != 1:
            continue
        home = event.get("home") or {}
        away = event.get("away") or {}
        _register_fotmob_side(match.home, home, 0.99, "unique_competition_kickoff")
        _register_fotmob_side(match.away, away, 0.99, "unique_competition_kickoff")


def _learn_one_sided_provider_aliases(
    matches: list[RawMatch],
    events_by_date: dict[str, list[dict[str, Any]]],
) -> None:
    """Learn the unknown opponent name when one side identifies one fixture.

    This is intentionally conservative: a local match must have exactly one
    provider fixture on its date where one side already matches strongly and
    the opposite provider side is still unknown. It improves new-team coverage
    without guessing from date alone.
    """
    for _ in range(2):
        changed = False
        for match in matches:
            events = _fotmob_events_for_match(match, events_by_date)
            candidates: list[tuple[str, str, str]] = []
            for event in events:
                distance = _fotmob_kickoff_distance_hours(match, event)
                if distance is not None and distance > 6.0:
                    continue
                home_side = event.get("home") or {}
                away_side = event.get("away") or {}
                home = str(home_side.get("name") or "")
                away = str(away_side.get("name") or "")
                local_home = _fotmob_side_score(match.home, home_side)
                local_away = _fotmob_side_score(match.away, away_side)
                if local_home >= 0.8 and local_away == 0.0:
                    candidates.append((match.away, away, str(away_side.get("id") or "")))
                elif local_away >= 0.8 and local_home == 0.0:
                    candidates.append((match.home, home, str(home_side.get("id") or "")))
                reverse_home = _fotmob_side_score(match.home, away_side)
                reverse_away = _fotmob_side_score(match.away, home_side)
                if reverse_home >= 0.8 and reverse_away == 0.0:
                    candidates.append((match.away, home, str(home_side.get("id") or "")))
                elif reverse_away >= 0.8 and reverse_home == 0.0:
                    candidates.append((match.home, away, str(away_side.get("id") or "")))
            unique = {(local, provider, provider_id) for local, provider, provider_id in candidates if provider}
            if len(unique) == 1:
                local, provider_name, provider_id = next(iter(unique))
                changed = register_team_alias(
                    local,
                    provider_name,
                    provider="fotmob",
                    provider_id=provider_id,
                    confidence=0.95,
                    source="one_sided_unique_fixture",
                ) or changed
        if not changed:
            break


def _learn_bilingual_provider_aliases(
    matches: list[RawMatch],
    events_by_date: dict[str, list[dict[str, Any]]],
    cache_dir: Path,
) -> None:
    """Resolve only ambiguous fixture groups through a bilingual entity source.

    A label is never persisted on its own. Both translated team labels must
    identify the same provider fixture and orientation inside the already
    constrained competition/kickoff candidate group.
    """
    unresolved: list[tuple[RawMatch, list[dict[str, Any]]]] = []
    names: set[str] = set()
    for match in matches:
        event, _, _ = _match_fotmob_event(match, events_by_date)
        if event:
            continue
        candidates = [
            item
            for item in _fotmob_events_for_match(match, events_by_date)
            if (distance := _fotmob_kickoff_distance_hours(match, item)) is not None and distance <= 0.25
        ]
        if len(candidates) <= 1 or len(candidates) > 40:
            continue
        unresolved.append((match, candidates))
        names.update((match.home, match.away))
    if not unresolved:
        return

    aliases_by_name: dict[str, tuple[str, ...]] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            name: executor.submit(fetch_dbpedia_club_aliases, name, cache_dir)
            for name in sorted(names)
        }
        for name, future in futures.items():
            try:
                aliases_by_name[name] = future.result()
            except (OSError, TimeoutError, urllib.error.URLError):
                aliases_by_name[name] = ()

    claimed_events: set[str] = set()
    for match, candidates in unresolved:
        home_aliases = aliases_by_name.get(match.home, ())
        away_aliases = aliases_by_name.get(match.away, ())
        if not home_aliases or not away_aliases:
            continue
        matches_found: list[tuple[dict[str, Any], bool]] = []
        for event in candidates:
            home_side = event.get("home") or {}
            away_side = event.get("away") or {}
            direct = _aliases_match_side(home_aliases, home_side) and _aliases_match_side(away_aliases, away_side)
            reverse = _aliases_match_side(home_aliases, away_side) and _aliases_match_side(away_aliases, home_side)
            if direct:
                matches_found.append((event, False))
            if reverse:
                matches_found.append((event, True))
        unique = {
            (str(event.get("id") or _fotmob_event_key(event)), reversed_sides)
            for event, reversed_sides in matches_found
        }
        if len(unique) != 1:
            continue
        event, reversed_sides = matches_found[0]
        event_key = _fotmob_event_key(event)
        if event_key in claimed_events:
            continue
        claimed_events.add(event_key)
        home_side = event.get("away" if reversed_sides else "home") or {}
        away_side = event.get("home" if reversed_sides else "away") or {}
        _register_fotmob_side(match.home, home_side, 0.98, "dbpedia_bilingual_fixture")
        _register_fotmob_side(match.away, away_side, 0.98, "dbpedia_bilingual_fixture")


def _aliases_match_side(aliases: tuple[str, ...], side: dict[str, Any]) -> bool:
    provider_names = (str(side.get("name") or ""), str(side.get("longName") or ""))
    return any(team_match_score(alias, provider_name) >= 0.8 for alias in aliases for provider_name in provider_names)


def _team_ref(local_name: str, side: str, event: dict[str, Any] | None, overrides: dict[str, int]) -> TeamRef | None:
    if local_name in overrides:
        return TeamRef(overrides[local_name], local_name)
    if not event:
        return None
    raw = event.get(side) or {}
    team_id = raw.get("id")
    name = raw.get("longName") or raw.get("name") or local_name
    return TeamRef(int(team_id), str(name)) if team_id else None


def _fotmob_side_score(local_name: str, side: dict[str, Any]) -> float:
    names = {str(side.get("name") or ""), str(side.get("longName") or "")}
    return max(provider_team_match_score(local_name, name, "fotmob", side.get("id")) for name in names)


def _remember_fotmob_side(local_name: str, side: dict[str, Any], diagnostic: dict[str, Any]) -> None:
    _register_fotmob_side(
        local_name,
        side,
        float(diagnostic.get("match_confidence") or 0.8),
        "matched_fixture_pair",
    )


def _register_fotmob_side(local_name: str, side: dict[str, Any], confidence: float, source: str) -> None:
    names = dict.fromkeys((str(side.get("name") or "").strip(), str(side.get("longName") or "").strip()))
    for name in names:
        if name:
            register_team_alias(
                local_name,
                name,
                provider="fotmob",
                provider_id=side.get("id"),
                confidence=confidence,
                source=source,
            )


def _fotmob_kickoff_distance_hours(match: RawMatch, event: dict[str, Any]) -> float | None:
    provider_value = str(((event.get("status") or {}).get("utcTime") or event.get("startTime") or ""))
    return _kickoff_distance_hours(match.kickoff, provider_value)


def _fotmob_events_for_match(
    match: RawMatch,
    events_by_date: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for date in _candidate_date_keys(match.kickoff):
        for event in events_by_date.get(date, ()):
            key = _fotmob_event_key(event)
            if key not in seen:
                seen.add(key)
                events.append(event)
    allowed = {normalize_team_name(name) for name in FOTMOB_LEAGUE_ALIASES.get(match.league, ())}
    tagged = [event for event in events if str(event.get("_provider_league_name") or "").strip()]
    if not allowed or not tagged:
        return events
    return [
        event
        for event in tagged
        if normalize_team_name(str(event.get("_provider_league_name") or "")) in allowed
    ]


def _fotmob_event_key(event: dict[str, Any]) -> str:
    event_id = str(event.get("id") or "").strip()
    if event_id:
        return event_id
    home = str((event.get("home") or {}).get("name") or "")
    away = str((event.get("away") or {}).get("name") or "")
    kickoff = str((event.get("status") or {}).get("utcTime") or "")
    return f"{kickoff}|{home}|{away}"


def _fixture_to_match_stat(item: dict[str, Any], team_id: int) -> MatchStat | None:
    home = item.get("home") or {}
    away = item.get("away") or {}
    if home.get("score") is None or away.get("score") is None:
        return None
    is_home = int(home.get("id", -1)) == team_id
    if not is_home and int(away.get("id", -1)) != team_id:
        return None
    gf = int(home["score"] if is_home else away["score"])
    ga = int(away["score"] if is_home else home["score"])
    result = "W" if gf > ga else "D" if gf == ga else "L"
    opponent = (away if is_home else home).get("name", "")
    return MatchStat(
        match_id=int(item["id"]),
        date=str((item.get("status") or {}).get("utcTime", "")),
        is_home=is_home,
        goals_for=gf,
        goals_against=ga,
        result=result,
        opponent=str(opponent),
    )


def _fetch_match_xg(
    match_id: int,
    team_id: int,
    cache: Path,
    match_details: dict[int, Any] | None = None,
) -> tuple[float, float] | None:
    payload = _match_details_payload(match_id, cache, 86400 * 30, match_details)
    if not payload or payload.get("error"):
        return None
    home_id = int(((payload.get("general") or {}).get("homeTeam") or {}).get("id", -1))
    away_id = int(((payload.get("general") or {}).get("awayTeam") or {}).get("id", -1))
    home_xg = 0.0
    away_xg = 0.0
    for event in _walk_dicts(payload):
        shot = event.get("shotmapEvent")
        if not isinstance(shot, dict) or "expectedGoals" not in shot:
            continue
        try:
            xg = float(shot["expectedGoals"])
        except (TypeError, ValueError):
            continue
        if int(shot.get("teamId", -1)) == home_id:
            home_xg += xg
        elif int(shot.get("teamId", -1)) == away_id:
            away_xg += xg
    if not home_xg and not away_xg:
        return None
    return (home_xg, away_xg) if team_id == home_id else (away_xg, home_xg)


def _extract_h2h_from_event(
    event: dict[str, Any],
    cache: Path,
    match_details: dict[int, Any] | None = None,
) -> tuple[str, ...]:
    match_id = event.get("id")
    if not match_id:
        return ()
    payload = _match_details_payload(int(match_id), cache, 3600, match_details)
    if not payload or payload.get("error"):
        return ()
    # Pre-match pages vary; keep this conservative and rely on team histories when absent.
    return ()


def _is_finished(item: dict[str, Any]) -> bool:
    return bool(((item.get("status") or {}).get("finished")))


def _match_details_payload(
    match_id: int,
    cache: Path,
    max_age_seconds: int,
    match_details: dict[int, Any] | None = None,
) -> Any:
    if match_details is not None and match_id in match_details:
        return match_details[match_id]
    payload = _fetch_json(
        f"{FOTMOB_BASE}/matchDetails?{urllib.parse.urlencode({'matchId': match_id})}",
        cache,
        max_age_seconds,
    )
    if match_details is not None:
        match_details[match_id] = payload
    return payload


def _fetch_json(url: str, cache: Path, max_age_seconds: int) -> Any:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    if path.exists():
        age = datetime.now().timestamp() - path.stat().st_mtime
        if age <= max_age_seconds:
            return _read_json_object(path)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "x-fm-req": "1"})
    try:
        text = read_url_text(req, timeout=12)
    except (OSError, urllib.error.URLError):
        if path.exists():
            return _read_json_object(path)
        return None
    path.write_text(text, encoding="utf-8")
    payload = loads_json(text)
    _remember_json_object(path, payload)
    return payload


def _read_json_object(path: Path) -> Any:
    stat = path.stat()
    key = str(path.absolute())
    signature = (stat.st_mtime_ns, stat.st_size)
    with _JSON_OBJECT_CACHE_LOCK:
        cached = _JSON_OBJECT_CACHE.get(key)
        if cached is not None and cached[:2] == signature:
            _JSON_OBJECT_CACHE.move_to_end(key)
            return cached[2]
    payload = loads_json(path.read_text(encoding="utf-8", errors="replace"))
    _remember_json_object(path, payload, signature=signature)
    return payload


def _remember_json_object(
    path: Path,
    payload: Any,
    *,
    signature: tuple[int, int] | None = None,
) -> None:
    if signature is None:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    key = str(path.absolute())
    with _JSON_OBJECT_CACHE_LOCK:
        _JSON_OBJECT_CACHE[key] = (signature[0], signature[1], payload)
        _JSON_OBJECT_CACHE.move_to_end(key)
        while len(_JSON_OBJECT_CACHE) > _JSON_OBJECT_CACHE_LIMIT:
            _JSON_OBJECT_CACHE.popitem(last=False)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _team_score(local: str, candidate: str) -> float:
    return team_match_score(local, candidate)


def _rating(win_rate: float, draw_rate: float, gf: float, ga: float, xgf: float | None, xga: float | None) -> float:
    xg_edge = 0.0 if xgf is None or xga is None else (xgf - xga) * 0.12
    return max(0.0, min(1.0, 0.35 + win_rate * 0.35 + draw_rate * 0.08 + (gf - ga) * 0.08 + xg_edge))


def _win_rate(games: list[MatchStat]) -> float | None:
    if not games:
        return None
    return round(sum(1 for item in games if item.result == "W") / len(games), 3)


def _rate_text(games: list[MatchStat]) -> str:
    rate = _win_rate(games)
    return "暂无" if rate is None else f"{rate:.0%}"


def _nullable(value: float | None) -> str:
    return "暂无" if value is None else f"{value:.2f}"


def _date_key(iso_value: str) -> str:
    return iso_value[:10].replace("-", "")


def _candidate_date_keys(iso_value: str) -> tuple[str, ...]:
    try:
        base = datetime.fromisoformat(iso_value).date()
    except ValueError:
        return (_date_key(iso_value),)
    dates = [base + timedelta(days=offset) for offset in (-1, 0, 1)]
    return tuple(item.strftime("%Y%m%d") for item in dates)


def _kickoff_distance_hours(first: str, second: str) -> float | None:
    try:
        first_time = datetime.fromisoformat(first.replace("Z", "+00:00"))
        second_time = datetime.fromisoformat(second.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if (first_time.tzinfo is None) != (second_time.tzinfo is None):
        return None
    return abs((first_time - second_time).total_seconds()) / 3600.0


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
