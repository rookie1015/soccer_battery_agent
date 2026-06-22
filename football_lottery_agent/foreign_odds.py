from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .collectors import OddsRow, RawMatch


THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
DEFAULT_REGIONS = "uk,eu"
DEFAULT_BOOKMAKERS = "pinnacle,betfair,unibet,williamhill,bet365,betvictor,paddypower,ladbrokes,coral,marathonbet"

LEAGUE_SPORT_KEYS = {
    "英超": ("soccer_epl",),
    "西甲": ("soccer_spain_la_liga",),
    "德甲": ("soccer_germany_bundesliga",),
    "意甲": ("soccer_italy_serie_a",),
    "法甲": ("soccer_france_ligue_one",),
    "欧冠": ("soccer_uefa_champs_league",),
    "欧联": ("soccer_uefa_europa_league",),
    "世界杯": ("soccer_fifa_world_cup",),
    "日职": ("soccer_japan_j_league",),
    "韩职": ("soccer_korea_kleague1",),
    "美职": ("soccer_usa_mls",),
}

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
    "乌兹别克": ("uzbekistan",),
    "英格兰": ("england",),
    "加纳": ("ghana",),
    "巴拿马": ("panama",),
    "克罗地亚": ("croatia",),
    "哥伦比亚": ("colombia",),
    "民主刚果": ("dr congo", "congo dr", "democratic republic of congo"),
}


@dataclass(frozen=True)
class ForeignOdds:
    odds: OddsRow
    bookmaker_count: int
    bookmakers: tuple[str, ...]
    matched_event: str
    sport_key: str
    spread: float
    raw: dict[str, Any]


def fetch_foreign_odds_for_matches(
    matches: list[RawMatch],
    cache_dir: str | Path,
    api_key: str | None = None,
    regions: str = DEFAULT_REGIONS,
    bookmakers: str = DEFAULT_BOOKMAKERS,
    sport_keys: tuple[str, ...] = (),
) -> dict[int, ForeignOdds]:
    key = api_key or os.getenv("THE_ODDS_API_KEY")
    if not key:
        return {}

    cache = Path(cache_dir) / "foreign_odds"
    candidate_sports = sport_keys or _sport_keys_for_matches(matches)
    events_by_sport = {
        sport_key: _fetch_the_odds_api(sport_key, key, regions, bookmakers, cache)
        for sport_key in candidate_sports
    }

    result: dict[int, ForeignOdds] = {}
    for match in matches:
        for sport_key in _match_sport_keys(match, candidate_sports):
            foreign = _match_event_to_odds(match, sport_key, events_by_sport.get(sport_key, []))
            if foreign:
                result[match.seq] = foreign
                break
    return result


def _fetch_the_odds_api(
    sport_key: str,
    api_key: str,
    regions: str,
    bookmakers: str,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = bookmakers
    url = f"{THE_ODDS_API_BASE}/sports/{sport_key}/odds?{urllib.parse.urlencode(params)}"
    try:
        text = _fetch_text(url, cache_dir, max_age_seconds=300)
        data = json.loads(text)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _match_event_to_odds(match: RawMatch, sport_key: str, events: list[dict[str, Any]]) -> ForeignOdds | None:
    best_event = None
    best_score = 0.0
    for event in events:
        score = _event_match_score(match, event)
        if score > best_score:
            best_score = score
            best_event = event
    if not best_event or best_score < 1.6:
        return None

    prices: list[tuple[float, float, float, str]] = []
    home_name = str(best_event.get("home_team", ""))
    away_name = str(best_event.get("away_team", ""))
    for bookmaker in best_event.get("bookmakers", []):
        market = next((item for item in bookmaker.get("markets", []) if item.get("key") == "h2h"), None)
        if not market:
            continue
        extracted = _extract_h2h_prices(market.get("outcomes", []), home_name, away_name)
        if extracted:
            prices.append((*extracted, str(bookmaker.get("key") or bookmaker.get("title") or "unknown")))
    if not prices:
        return None

    home = sum(item[0] for item in prices) / len(prices)
    draw = sum(item[1] for item in prices) / len(prices)
    away = sum(item[2] for item in prices) / len(prices)
    flat = [value for item in prices for value in item[:3]]
    spread = max(flat) - min(flat)
    return ForeignOdds(
        odds=OddsRow(seq=match.seq, home=round(home, 3), draw=round(draw, 3), away=round(away, 3)),
        bookmaker_count=len(prices),
        bookmakers=tuple(item[3] for item in prices),
        matched_event=f"{home_name} vs {away_name}",
        sport_key=sport_key,
        spread=round(spread, 3),
        raw={
            "event_id": best_event.get("id", ""),
            "commence_time": best_event.get("commence_time", ""),
            "bookmaker_count": len(prices),
            "bookmakers": [item[3] for item in prices],
        },
    )


def _extract_h2h_prices(outcomes: list[dict[str, Any]], home_name: str, away_name: str) -> tuple[float, float, float] | None:
    prices: dict[str, float] = {}
    for outcome in outcomes:
        name = str(outcome.get("name", ""))
        try:
            price = float(outcome["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if _same_name(name, home_name):
            prices["home"] = price
        elif _same_name(name, away_name):
            prices["away"] = price
        elif _normalize_name(name) == "draw":
            prices["draw"] = price
    if {"home", "draw", "away"} <= prices.keys():
        return prices["home"], prices["draw"], prices["away"]
    return None


def _event_match_score(match: RawMatch, event: dict[str, Any]) -> float:
    home = str(event.get("home_team", ""))
    away = str(event.get("away_team", ""))
    direct = _team_match_score(match.home, home) + _team_match_score(match.away, away)
    reversed_score = _team_match_score(match.home, away) + _team_match_score(match.away, home) - 0.4
    return max(direct, reversed_score)


def _team_match_score(local_name: str, foreign_name: str) -> float:
    local_norm = _normalize_name(local_name)
    foreign_norm = _normalize_name(foreign_name)
    if local_norm and local_norm == foreign_norm:
        return 1.0
    for alias in TEAM_ALIASES.get(local_name, ()):
        alias_norm = _normalize_name(alias)
        if alias_norm == foreign_norm or alias_norm in foreign_norm or foreign_norm in alias_norm:
            return 1.0
    if local_norm and (local_norm in foreign_norm or foreign_norm in local_norm):
        return 0.8
    return 0.0


def _sport_keys_for_matches(matches: list[RawMatch]) -> tuple[str, ...]:
    keys = []
    for match in matches:
        for key in LEAGUE_SPORT_KEYS.get(match.league, ()):
            if key not in keys:
                keys.append(key)
    return tuple(keys)


def _match_sport_keys(match: RawMatch, fallback: tuple[str, ...]) -> tuple[str, ...]:
    mapped = LEAGUE_SPORT_KEYS.get(match.league, ())
    return mapped or fallback


def _same_name(a: str, b: str) -> bool:
    return _normalize_name(a) == _normalize_name(b)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _fetch_text(url: str, cache_dir: Path, max_age_seconds: int) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{abs(hash(url))}.json"
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            return cache_path.read_text(encoding="utf-8", errors="replace")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        text = response.read().decode("utf-8", errors="replace")
    cache_path.write_text(text, encoding="utf-8")
    return text
