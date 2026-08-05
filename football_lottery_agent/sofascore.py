from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .json_utils import loads_json
from .team_identity import provider_team_match_score, register_team_alias


SOFASCORE_BASE = "https://www.sofascore.com/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SofaScoreTeamProfile:
    team_id: int
    team_name: str
    matches_used: int
    xg_matches_used: int
    win_rate: float
    draw_rate: float
    loss_rate: float
    home_win_rate: float | None
    away_win_rate: float | None
    goals_for_per_match: float
    goals_against_per_match: float
    xg_for_per_match: float | None
    xg_against_per_match: float | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SofaScoreFixtureStrength:
    home: SofaScoreTeamProfile | None
    away: SofaScoreTeamProfile | None
    source: dict[str, Any]


@dataclass(frozen=True)
class _RecentMatch:
    event_id: int
    timestamp: int
    is_home: bool
    goals_for: int
    goals_against: int


class SofaScoreClient:
    """Small cached client for SofaScore's web data endpoints.

    SofaScore does not document these endpoints as a stable public API. Every
    response is cached and a 403 opens a circuit breaker for the rest of the
    collection run. Stale cache entries remain usable so an upstream block does
    not erase previously collected model inputs.
    """

    def __init__(self, cache_dir: str | Path):
        self.cache = Path(cache_dir) / "sofascore"
        self.blocked = False

    def fetch(self, path: str, max_age_seconds: int) -> Any:
        url = f"{SOFASCORE_BASE}{path}"
        cache_path = self._cache_path(url)
        cached = self._read_cache(cache_path)
        if cached is not None and self._is_fresh(cache_path, max_age_seconds):
            return cached
        if self.blocked:
            return cached

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.sofascore.com/",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 429}:
                self.blocked = True
            return cached
        except (OSError, urllib.error.URLError):
            return cached

        try:
            payload = loads_json(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return cached
        self.cache.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return payload

    def _cache_path(self, url: str) -> Path:
        return self.cache / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"

    @staticmethod
    def _is_fresh(path: Path, max_age_seconds: int) -> bool:
        return path.exists() and datetime.now().timestamp() - path.stat().st_mtime <= max_age_seconds

    @staticmethod
    def _read_cache(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return loads_json(path.read_text(encoding="utf-8", errors="replace"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


def build_sofascore_for_matches(
    matches: list[Any],
    cache_dir: str | Path,
    lookback: int,
    xg_matches: int,
    team_score: Callable[[str, str], float],
) -> dict[int, SofaScoreFixtureStrength]:
    client = SofaScoreClient(cache_dir)
    events_by_date = _fetch_events_for_dates(matches, client)
    result: dict[int, SofaScoreFixtureStrength] = {}
    profile_cache: dict[int, SofaScoreTeamProfile | None] = {}

    for match in matches:
        event, reversed_sides, match_diagnostic = _match_event(match, events_by_date, team_score)
        if not event:
            result[match.seq] = SofaScoreFixtureStrength(
                home=None,
                away=None,
                source={
                    "provider": "sofascore",
                    "status": "blocked" if client.blocked else "unmatched",
                    **match_diagnostic,
                },
            )
            continue

        event_home = event.get("homeTeam") or {}
        event_away = event.get("awayTeam") or {}
        local_home = event_away if reversed_sides else event_home
        local_away = event_home if reversed_sides else event_away
        home_id = _integer(local_home.get("id"))
        away_id = _integer(local_away.get("id"))
        _remember_sofascore_side(match.home, local_home, match_diagnostic)
        _remember_sofascore_side(match.away, local_away, match_diagnostic)
        home = _profile_for_team(home_id, local_home, client, lookback, xg_matches, profile_cache)
        away = _profile_for_team(away_id, local_away, client, lookback, xg_matches, profile_cache)
        result[match.seq] = SofaScoreFixtureStrength(
            home=home,
            away=away,
            source={
                "provider": "sofascore",
                "status": "cached_or_live",
                "matched_event_id": event.get("id"),
                "home_team_id": home_id,
                "away_team_id": away_id,
                "lookback": lookback,
                "xg_matches": xg_matches,
                **match_diagnostic,
            },
        )
    return result


def _fetch_events_for_dates(matches: list[Any], client: SofaScoreClient) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for date in sorted({item for match in matches for item in _candidate_dates(match.kickoff)}):
        payload = client.fetch(f"/sport/football/scheduled-events/{date}", 3600)
        result[date] = list((payload or {}).get("events") or [])
    return result


def _match_event(
    match: Any,
    events_by_date: dict[str, list[dict[str, Any]]],
    team_score: Callable[[str, str], float],
) -> tuple[dict[str, Any] | None, bool, dict[str, Any]]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    best_reversed = False
    events: list[dict[str, Any]] = []
    for date in _candidate_dates(match.kickoff):
        events.extend(events_by_date.get(date, ()))

    for event in events:
        home_name = str((event.get("homeTeam") or {}).get("name") or "")
        away_name = str((event.get("awayTeam") or {}).get("name") or "")
        home_side = event.get("homeTeam") or {}
        away_side = event.get("awayTeam") or {}
        direct = _sofascore_side_score(match.home, home_side, team_score) + _sofascore_side_score(match.away, away_side, team_score)
        reverse = _sofascore_side_score(match.home, away_side, team_score) + _sofascore_side_score(match.away, home_side, team_score) - 0.3
        score = max(direct, reverse)
        if score > best_score:
            best = event
            best_score = score
            best_reversed = reverse > direct
    matched = best is not None and best_score >= 1.6
    diagnostic = {
        "match_status": "matched" if matched else "unmatched",
        "match_confidence": round(max(0.0, min(1.0, best_score / 2.0)), 3),
        "match_reason": "provider_id_or_alias_pair" if matched else ("low_confidence" if best else "no_candidates"),
        "candidate_event_id": (best or {}).get("id", ""),
        "candidate_home": str(((best or {}).get("homeTeam") or {}).get("name") or ""),
        "candidate_away": str(((best or {}).get("awayTeam") or {}).get("name") or ""),
    }
    return (best, best_reversed, diagnostic) if matched else (None, False, diagnostic)


def _sofascore_side_score(
    local_name: str,
    side: dict[str, Any],
    fallback_score: Callable[[str, str], float],
) -> float:
    name = str(side.get("name") or "")
    if side.get("id") is not None:
        return provider_team_match_score(local_name, name, "sofascore", side.get("id"))
    return fallback_score(local_name, name)


def _remember_sofascore_side(local_name: str, side: dict[str, Any], diagnostic: dict[str, Any]) -> None:
    register_team_alias(
        local_name,
        str(side.get("name") or ""),
        provider="sofascore",
        provider_id=side.get("id"),
        confidence=float(diagnostic.get("match_confidence") or 0.8),
        source="matched_fixture_pair",
    )


def _profile_for_team(
    team_id: int | None,
    team: dict[str, Any],
    client: SofaScoreClient,
    lookback: int,
    xg_matches: int,
    profile_cache: dict[int, SofaScoreTeamProfile | None],
) -> SofaScoreTeamProfile | None:
    if team_id is None:
        return None
    if team_id in profile_cache:
        return profile_cache[team_id]

    events: list[dict[str, Any]] = []
    page = 0
    while len(events) < lookback and page < 3:
        payload = client.fetch(f"/team/{team_id}/events/last/{page}", 21600)
        page_events = list((payload or {}).get("events") or [])
        if not page_events:
            break
        events.extend(event for event in page_events if _is_finished(event))
        if not (payload or {}).get("hasNextPage"):
            break
        page += 1

    unique: dict[int, _RecentMatch] = {}
    for item in (_to_recent_match(event, team_id) for event in events):
        if item is not None:
            unique[item.event_id] = item
    recent = sorted(unique.values(), key=lambda item: item.timestamp, reverse=True)[:lookback]
    if not recent:
        profile_cache[team_id] = None
        return None

    anchor = recent[0].timestamp
    match_weights = [_time_weight(item.timestamp, anchor) for item in recent]
    goals_for = _weighted_average([float(item.goals_for) for item in recent], match_weights)
    goals_against = _weighted_average([float(item.goals_against) for item in recent], match_weights)
    win_rate = _weighted_average([float(item.goals_for > item.goals_against) for item in recent], match_weights)
    draw_rate = _weighted_average([float(item.goals_for == item.goals_against) for item in recent], match_weights)
    loss_rate = max(0.0, 1.0 - win_rate - draw_rate)
    home_win_rate = _side_win_rate(recent, match_weights, True)
    away_win_rate = _side_win_rate(recent, match_weights, False)

    xg_samples: list[tuple[float, float, float]] = []
    for item, weight in zip(recent[:xg_matches], match_weights[:xg_matches]):
        values = _event_xg(item.event_id, item.is_home, client)
        if values is not None:
            xg_samples.append((values[0], values[1], weight))
    xgf = _weighted_average([item[0] for item in xg_samples], [item[2] for item in xg_samples]) if xg_samples else None
    xga = _weighted_average([item[1] for item in xg_samples], [item[2] for item in xg_samples]) if xg_samples else None
    name = str(team.get("name") or team_id)
    notes = (
        f"{name} SofaScore近{len(recent)}场加权场均进{goals_for:.2f}/失{goals_against:.2f}。",
        f"SofaScore xG样本 {len(xg_samples)} 场：{_nullable(xgf)} / {_nullable(xga)}。",
    )
    profile = SofaScoreTeamProfile(
        team_id=team_id,
        team_name=name,
        matches_used=len(recent),
        xg_matches_used=len(xg_samples),
        win_rate=round(win_rate, 3),
        draw_rate=round(draw_rate, 3),
        loss_rate=round(loss_rate, 3),
        home_win_rate=_rounded(home_win_rate),
        away_win_rate=_rounded(away_win_rate),
        goals_for_per_match=round(goals_for, 3),
        goals_against_per_match=round(goals_against, 3),
        xg_for_per_match=_rounded(xgf),
        xg_against_per_match=_rounded(xga),
        notes=notes,
    )
    profile_cache[team_id] = profile
    return profile


def _event_xg(event_id: int, team_is_home: bool, client: SofaScoreClient) -> tuple[float, float] | None:
    statistics = client.fetch(f"/event/{event_id}/statistics", 86400 * 30)
    home_away = _xg_from_statistics(statistics)
    if home_away is None:
        shotmap = client.fetch(f"/event/{event_id}/shotmap", 86400 * 30)
        home_away = _xg_from_shotmap(shotmap)
    if home_away is None:
        return None
    return home_away if team_is_home else (home_away[1], home_away[0])


def _xg_from_statistics(payload: Any) -> tuple[float, float] | None:
    for item in _walk_dicts(payload):
        name = str(item.get("name") or item.get("key") or "").lower().replace(" ", "")
        if name not in {"expectedgoals", "expectedgoal", "xg"}:
            continue
        home = _number(item.get("home"))
        away = _number(item.get("away"))
        if home is not None and away is not None:
            return home, away
    return None


def _xg_from_shotmap(payload: Any) -> tuple[float, float] | None:
    shots = list((payload or {}).get("shotmap") or [])
    home_xg = 0.0
    away_xg = 0.0
    samples = 0
    for shot in shots:
        xg = _number(shot.get("xg"))
        if xg is None:
            xg = _number(shot.get("expectedGoals"))
        if xg is None:
            continue
        samples += 1
        if _boolean(shot.get("isHome")):
            home_xg += xg
        else:
            away_xg += xg
    return (home_xg, away_xg) if samples else None


def _to_recent_match(event: dict[str, Any], team_id: int) -> _RecentMatch | None:
    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    home_id = _integer(home.get("id"))
    away_id = _integer(away.get("id"))
    if team_id not in {home_id, away_id}:
        return None
    home_score = _score_value(event.get("homeScore"))
    away_score = _score_value(event.get("awayScore"))
    event_id = _integer(event.get("id"))
    timestamp = _integer(event.get("startTimestamp"))
    if None in {home_score, away_score, event_id, timestamp}:
        return None
    is_home = home_id == team_id
    return _RecentMatch(
        event_id=event_id,
        timestamp=timestamp,
        is_home=is_home,
        goals_for=home_score if is_home else away_score,
        goals_against=away_score if is_home else home_score,
    )


def _score_value(value: Any) -> int | None:
    if not isinstance(value, dict):
        return _integer(value)
    for key in ("normaltime", "current", "display"):
        parsed = _integer(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _is_finished(event: dict[str, Any]) -> bool:
    status = str((event.get("status") or {}).get("type") or "").lower()
    return status in {"finished", "afterextra", "afterpenalties"}


def _candidate_dates(value: str) -> tuple[str, ...]:
    try:
        base = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return (value[:10],)
    return tuple((base + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1))


def _time_weight(timestamp: int, anchor: int) -> float:
    age_days = max(0.0, (anchor - timestamp) / 86400.0)
    return 0.5 ** (age_days / 60.0)


def _side_win_rate(matches: list[_RecentMatch], weights: list[float], is_home: bool) -> float | None:
    selected = [
        (float(item.goals_for > item.goals_against), weight)
        for item, weight in zip(matches, weights)
        if item.is_home == is_home
    ]
    if not selected:
        return None
    return _weighted_average([item[0] for item in selected], [item[1] for item in selected])


def _weighted_average(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return sum(value * weight for value, weight in zip(values, weights)) / total if total > 0 else 0.0


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _nullable(value: float | None) -> str:
    return "暂无" if value is None else f"{value:.2f}"
