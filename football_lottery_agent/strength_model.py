from __future__ import annotations

import csv
import hashlib
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .collectors import RawMatch
from .json_utils import loads_json


FOTMOB_BASE = "https://www.fotmob.com/api/data"

TEAM_ALIASES = {
    "荷兰": ("netherlands", "holland"),
    "瑞典": ("sweden",),
    "德国": ("germany",),
    "科特迪瓦": ("ivory coast", "cote d ivoire", "côte d'ivoire"),
    "突尼斯": ("tunisia",),
    "日本": ("japan",),
    "西班牙": ("spain",),
    "沙特": ("saudi arabia", "saudi"),
    "乌拉圭": ("uruguay",),
    "佛得角": ("cape verde",),
    "新西兰": ("new zealand",),
    "埃及": ("egypt",),
    "阿根廷": ("argentina",),
    "奥地利": ("austria",),
    "法国": ("france",),
    "伊拉克": ("iraq",),
    "挪威": ("norway",),
    "塞内加尔": ("senegal",),
    "约旦": ("jordan",),
    "阿尔及利亚": ("algeria",),
    "葡萄牙": ("portugal",),
    "乌兹别克": ("uzbekistan", "uzbekistan u20"),
    "英格兰": ("england",),
    "加纳": ("ghana",),
    "巴拿马": ("panama",),
    "克罗地亚": ("croatia",),
    "哥伦比亚": ("colombia",),
    "民主刚果": ("dr congo", "congo dr", "democratic republic of congo"),
    "曼城": ("manchester city", "man city"),
    "热刺": ("tottenham hotspur", "tottenham", "spurs"),
    "皇家社会": ("real sociedad",),
    "比利亚雷亚尔": ("villarreal",),
    "多特蒙德": ("borussia dortmund", "dortmund"),
    "法兰克福": ("eintracht frankfurt", "frankfurt"),
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
    goals_for_per_match: float
    goals_against_per_match: float
    xg_for_per_match: float | None
    xg_against_per_match: float | None
    rating: float
    notes: tuple[str, ...]


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
    cache = Path(cache_dir) / "fotmob"
    id_overrides = load_team_ids(team_ids_path) if team_ids_path else {}
    fotmob_events = _fetch_events_for_dates(matches, cache)

    result: dict[int, FixtureStrength] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_build_fixture_strength, match, cache, id_overrides, fotmob_events, lookback, xg_matches)
            for match in matches
        ]
        for match, future in zip(matches, futures):
            result[match.seq] = future.result()
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
    event = _match_fotmob_event(match, fotmob_events)
    home_ref = _team_ref(match.home, "home", event, id_overrides)
    away_ref = _team_ref(match.away, "away", event, id_overrides)

    home = _build_team_profile(home_ref, cache, lookback, xg_matches) if home_ref else None
    away = _build_team_profile(away_ref, cache, lookback, xg_matches) if away_ref else None
    unavailable = _fixture_unavailable(event, cache)
    home_squad = _build_squad_profile(home_ref, cache, unavailable.get("home", ())) if home_ref else None
    away_squad = _build_squad_profile(away_ref, cache, unavailable.get("away", ())) if away_ref else None
    h2h = _extract_h2h_from_event(event, cache) if event else ()
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
        },
    )


def _build_team_profile(team: TeamRef, cache: Path, lookback: int, xg_matches: int) -> StrengthProfile | None:
    team_data = _fetch_json(f"{FOTMOB_BASE}/teams?{urllib.parse.urlencode({'id': team.id})}", cache, 86400)
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
        xg = _fetch_match_xg(item.match_id, team.id, cache)
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
        goals_for_per_match=round(gf, 3),
        goals_against_per_match=round(ga, 3),
        xg_for_per_match=round(xgf, 3) if xgf is not None else None,
        xg_against_per_match=round(xga, 3) if xga is not None else None,
        rating=round(rating, 3),
        notes=notes,
    )


def _build_squad_profile(team: TeamRef, cache: Path, fixture_unavailable: tuple[dict[str, Any], ...]) -> SquadProfile | None:
    team_data = _fetch_json(f"{FOTMOB_BASE}/teams?{urllib.parse.urlencode({'id': team.id})}", cache, 86400)
    groups = (((team_data or {}).get("squad") or {}).get("squad")) or []
    players = [member for group in groups for member in (group.get("members") or []) if _is_player(member)]
    if len(players) < 11:
        return None

    unavailable_ids = {str(item.get("id")) for item in fixture_unavailable if item.get("id") is not None}
    unavailable_ids.update(str(player.get("id")) for player in players if _has_injury(player.get("injury")))
    unavailable_players = [player for player in players if str(player.get("id")) in unavailable_ids]
    available_players = [player for player in players if str(player.get("id")) not in unavailable_ids]
    recent_forms = _recent_player_forms(team, team_data, cache)
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


def _fixture_unavailable(event: dict[str, Any] | None, cache: Path) -> dict[str, tuple[dict[str, Any], ...]]:
    if not event or _is_finished(event) or not event.get("id"):
        return {"home": (), "away": ()}
    payload = _fetch_json(
        f"{FOTMOB_BASE}/matchDetails?{urllib.parse.urlencode({'matchId': event['id']})}", cache, 900
    )
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


def _recent_player_forms(team: TeamRef, team_data: dict[str, Any], cache: Path, limit: int = 8) -> dict[str, tuple[int, float]]:
    fixtures = (((team_data.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures")) or []
    finished = [_fixture_to_match_stat(item, team.id) for item in fixtures if _is_finished(item)]
    recent = sorted((item for item in finished if item is not None), key=lambda item: item.date, reverse=True)[:limit]
    values: dict[str, list[float]] = {}
    for item in recent:
        payload = _fetch_json(
            f"{FOTMOB_BASE}/matchDetails?{urllib.parse.urlencode({'matchId': item.match_id})}", cache, 86400 * 30
        )
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
            events.extend(league.get("matches", []))
        result[date] = events
    return result


def _match_fotmob_event(match: RawMatch, events_by_date: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    best = None
    best_score = 0.0
    events = []
    for date in _candidate_date_keys(match.kickoff):
        events.extend(events_by_date.get(date, []))
    for event in events:
        score = _team_score(match.home, event.get("home", {}).get("name", "")) + _team_score(match.away, event.get("away", {}).get("name", ""))
        reverse = _team_score(match.home, event.get("away", {}).get("name", "")) + _team_score(match.away, event.get("home", {}).get("name", "")) - 0.3
        score = max(score, reverse)
        if score > best_score:
            best_score = score
            best = event
    return best if best_score >= 1.6 else None


def _team_ref(local_name: str, side: str, event: dict[str, Any] | None, overrides: dict[str, int]) -> TeamRef | None:
    if local_name in overrides:
        return TeamRef(overrides[local_name], local_name)
    if not event:
        return None
    raw = event.get(side) or {}
    team_id = raw.get("id")
    name = raw.get("longName") or raw.get("name") or local_name
    return TeamRef(int(team_id), str(name)) if team_id else None


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


def _fetch_match_xg(match_id: int, team_id: int, cache: Path) -> tuple[float, float] | None:
    payload = _fetch_json(f"{FOTMOB_BASE}/matchDetails?{urllib.parse.urlencode({'matchId': match_id})}", cache, 86400 * 30)
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


def _extract_h2h_from_event(event: dict[str, Any], cache: Path) -> tuple[str, ...]:
    match_id = event.get("id")
    if not match_id:
        return ()
    payload = _fetch_json(f"{FOTMOB_BASE}/matchDetails?{urllib.parse.urlencode({'matchId': match_id})}", cache, 3600)
    if not payload or payload.get("error"):
        return ()
    # Pre-match pages vary; keep this conservative and rely on team histories when absent.
    return ()


def _is_finished(item: dict[str, Any]) -> bool:
    return bool(((item.get("status") or {}).get("finished")))


def _fetch_json(url: str, cache: Path, max_age_seconds: int) -> Any:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    if path.exists():
        age = datetime.now().timestamp() - path.stat().st_mtime
        if age <= max_age_seconds:
            return loads_json(path.read_text(encoding="utf-8", errors="replace"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "x-fm-req": "1"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        if path.exists():
            return loads_json(path.read_text(encoding="utf-8", errors="replace"))
        return None
    path.write_text(text, encoding="utf-8")
    return loads_json(text)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _team_score(local: str, candidate: str) -> float:
    candidate_norm = _normalize(candidate)
    for alias in (local, *TEAM_ALIASES.get(local, ())):
        alias_norm = _normalize(alias)
        if alias_norm == candidate_norm:
            return 1.0
        if alias_norm and (alias_norm in candidate_norm or candidate_norm in alias_norm):
            return 0.8
    return 0.0


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


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
