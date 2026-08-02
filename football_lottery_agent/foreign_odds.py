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
from .json_utils import loads_json
from .team_identity import team_match_score


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

@dataclass(frozen=True)
class ForeignOdds:
    odds: OddsRow
    bookmaker_count: int
    bookmakers: tuple[str, ...]
    matched_event: str
    sport_key: str
    spread: float
    raw: dict[str, Any]


def check_the_odds_api_usage(api_key: str | None) -> dict[str, Any]:
    key = str(api_key or "").strip()
    if not key:
        return {
            "status": "not_configured",
            "message": "尚未填写 The Odds API Key。",
            "credits_remaining": None,
            "credits_used": None,
            "credits_last": None,
            "active_sports": 0,
        }
    url = f"{THE_ODDS_API_BASE}/sports/?{urllib.parse.urlencode({'apiKey': key})}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = loads_json(body)
            if not isinstance(payload, list):
                return {
                    "status": "provider_error",
                    "message": "The Odds API 返回格式异常。",
                    "credits_remaining": _header_int(response.headers, "x-requests-remaining"),
                    "credits_used": _header_int(response.headers, "x-requests-used"),
                    "credits_last": _header_int(response.headers, "x-requests-last"),
                    "active_sports": 0,
                }
            return {
                "status": "valid",
                "message": "The Odds API Key 有效。用量查询本身不消耗额度。",
                "credits_remaining": _header_int(response.headers, "x-requests-remaining"),
                "credits_used": _header_int(response.headers, "x-requests-used"),
                "credits_last": _header_int(response.headers, "x-requests-last"),
                "active_sports": len(payload),
                "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
    except urllib.error.HTTPError as exc:
        error = _http_error_status(exc)
        messages = {
            "out_of_credits": "The Odds API Key 有效，但当前额度已用完。",
            "invalid_key": "The Odds API Key 无效或无权限。",
            "rate_limited": "The Odds API 请求过于频繁，请稍后再试。",
        }
        return {
            "status": error.get("status", "http_error"),
            "message": messages.get(str(error.get("status")), str(error.get("message") or "用量查询失败。")),
            "credits_remaining": error.get("credits_remaining"),
            "credits_used": error.get("credits_used"),
            "credits_last": error.get("credits_last"),
            "active_sports": 0,
        }
    except (OSError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "status": "network_error",
            "message": f"无法连接 The Odds API：{reason}",
            "credits_remaining": None,
            "credits_used": None,
            "credits_last": None,
            "active_sports": 0,
        }
    except json.JSONDecodeError:
        return {
            "status": "invalid_response",
            "message": "The Odds API 返回了无法解析的数据。",
            "credits_remaining": None,
            "credits_used": None,
            "credits_last": None,
            "active_sports": 0,
        }


def fetch_foreign_odds_for_matches(
    matches: list[RawMatch],
    cache_dir: str | Path,
    api_key: str | None = None,
    regions: str = DEFAULT_REGIONS,
    bookmakers: str = DEFAULT_BOOKMAKERS,
    sport_keys: tuple[str, ...] = (),
    audit: dict[str, Any] | None = None,
) -> dict[int, ForeignOdds]:
    key = api_key or os.getenv("THE_ODDS_API_KEY")
    status = audit if audit is not None else {}
    status.update(
        {
            "provider": "the_odds_api",
            "requested": True,
            "configured": bool(key),
            "status": "not_configured" if not key else "pending",
            "message": "未配置 The Odds API Key，本次未调用外盘。" if not key else "正在查询 The Odds API。",
            "queries_considered": 0,
            "attempted_queries": 0,
            "successful_queries": 0,
            "cache_hits": 0,
            "events_received": 0,
            "matched_matches": 0,
            "total_matches": len(matches),
            "credits_remaining": None,
            "credits_used": None,
            "credits_last": None,
            "query_errors": [],
        }
    )
    if not key:
        return {}

    cache = Path(cache_dir) / "foreign_odds"
    candidate_sports = sport_keys or _sport_keys_for_matches(matches)
    status["queried_sports"] = list(candidate_sports)
    if not candidate_sports:
        status.update(
            status="no_supported_leagues",
            message="本期联赛没有可用的 The Odds API sport key，本次未发出外盘请求。",
        )
        return {}

    events_by_sport: dict[str, list[dict[str, Any]]] = {}
    query_audits: list[dict[str, Any]] = []
    for sport_key in candidate_sports:
        query_audit: dict[str, Any] = {}
        events_by_sport[sport_key] = _fetch_the_odds_api(
            sport_key,
            key,
            regions,
            bookmakers,
            cache,
            audit=query_audit,
        )
        query_audits.append(query_audit)

    status["queries_considered"] = len(query_audits)
    status["attempted_queries"] = sum(1 for item in query_audits if item.get("live_attempted"))
    status["successful_queries"] = sum(
        1 for item in query_audits if item.get("source") == "live" and item.get("status") in {"success", "no_events"}
    )
    status["cache_hits"] = sum(1 for item in query_audits if item.get("source") == "cache")
    status["events_received"] = sum(int(item.get("event_count") or 0) for item in query_audits)
    status["query_errors"] = [
        {"sport_key": item.get("sport_key", ""), "status": item.get("status", ""), "message": item.get("message", "")}
        for item in query_audits
        if item.get("status") not in {"success", "no_events"}
    ]
    for field in ("credits_remaining", "credits_used", "credits_last"):
        values = [item[field] for item in query_audits if item.get(field) is not None]
        if values:
            status[field] = values[-1]

    result: dict[int, ForeignOdds] = {}
    for match in matches:
        for sport_key in _match_sport_keys(match, candidate_sports):
            foreign = _match_event_to_odds(match, sport_key, events_by_sport.get(sport_key, []))
            if foreign:
                result[match.seq] = foreign
                break
    status["matched_matches"] = len(result)
    _finalize_audit_status(status)
    return result


def _fetch_the_odds_api(
    sport_key: str,
    api_key: str,
    regions: str,
    bookmakers: str,
    cache_dir: Path,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    query_audit = audit if audit is not None else {}
    query_audit.update(
        {
            "sport_key": sport_key,
            "source": "none",
            "live_attempted": False,
            "status": "pending",
            "message": "",
            "event_count": 0,
            "credits_remaining": None,
            "credits_used": None,
            "credits_last": None,
        }
    )
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = bookmakers
    url = f"{THE_ODDS_API_BASE}/sports/{sport_key}/odds?{urllib.parse.urlencode(params)}"
    try:
        text, response_status = _fetch_text_with_status(url, cache_dir, max_age_seconds=300)
        query_audit.update(response_status)
        data = loads_json(text)
    except urllib.error.HTTPError as exc:
        query_audit.update(_http_error_status(exc))
        return []
    except urllib.error.URLError as exc:
        query_audit.update(
            source="live",
            live_attempted=True,
            status="network_error",
            message=f"网络连接失败：{exc.reason}",
        )
        return []
    except OSError as exc:
        query_audit.update(
            source="live",
            live_attempted=True,
            status="network_error",
            message=f"网络连接失败：{exc}",
        )
        return []
    except json.JSONDecodeError:
        query_audit.update(status="invalid_response", message="The Odds API 返回了无法解析的数据。")
        return []
    if not isinstance(data, list):
        provider_message = str(data.get("message") or data.get("error") or "") if isinstance(data, dict) else ""
        query_audit.update(status="provider_error", message=provider_message or "The Odds API 返回格式异常。")
        return []
    query_audit["event_count"] = len(data)
    query_audit["status"] = "success" if data else "no_events"
    query_audit["message"] = "已取得外盘赛事。" if data else "API 调用成功，但当前没有返回赛事。"
    return data


def _finalize_audit_status(audit: dict[str, Any]) -> None:
    matched = int(audit.get("matched_matches") or 0)
    attempted = int(audit.get("attempted_queries") or 0)
    successful = int(audit.get("successful_queries") or 0)
    cache_hits = int(audit.get("cache_hits") or 0)
    events = int(audit.get("events_received") or 0)
    total = int(audit.get("total_matches") or 0)
    errors = list(audit.get("query_errors") or [])

    if matched:
        if successful:
            audit["status"] = "success_live"
            audit["message"] = f"本次已联网调用 The Odds API，外盘匹配 {matched}/{total} 场。"
        else:
            audit["status"] = "success_cache"
            audit["message"] = f"本次未重复联网，使用 5 分钟内缓存的外盘数据，匹配 {matched}/{total} 场。"
        if errors:
            audit["message"] += f"另有 {len(errors)} 个联赛查询失败。"
        return

    error_priority = (
        "out_of_credits",
        "invalid_key",
        "rate_limited",
        "network_error",
        "invalid_response",
        "provider_error",
        "http_error",
    )
    for error_status in error_priority:
        error = next((item for item in errors if item.get("status") == error_status), None)
        if error:
            audit["status"] = error_status
            audit["message"] = str(error.get("message") or "外盘请求失败。")
            return

    if events:
        audit["status"] = "called_no_match" if attempted else "cache_no_match"
        prefix = "本次已联网调用" if attempted else "本次使用缓存"
        audit["message"] = f"{prefix} The Odds API 并取得 {events} 场赛事，但未能与本期对阵匹配。"
    else:
        audit["status"] = "called_no_events" if attempted else "cache_no_events"
        prefix = "本次已联网调用" if attempted else ("本次读取了缓存" if cache_hits else "本次未调用")
        audit["message"] = f"{prefix} The Odds API，但没有取得可用赛事。"


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
    probability_rows = [_normalized_probabilities(item[0], item[1], item[2]) for item in prices]
    consensus = {
        outcome: round(sum(row[outcome] for row in probability_rows) / len(probability_rows), 6)
        for outcome in ("3", "1", "0")
    }
    dispersion = {
        outcome: round(max(row[outcome] for row in probability_rows) - min(row[outcome] for row in probability_rows), 4)
        for outcome in ("3", "1", "0")
    }
    spread_summary = _average_spread_market(best_event.get("bookmakers", []), home_name)
    totals_summary = _average_totals_market(best_event.get("bookmakers", []))
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
            "market_consensus": consensus,
            "market_dispersion": dispersion,
            **spread_summary,
            **totals_summary,
        },
    )


def _normalized_probabilities(home: float, draw: float, away: float) -> dict[str, float]:
    implied = {"3": 1.0 / home, "1": 1.0 / draw, "0": 1.0 / away}
    total = sum(implied.values())
    return {outcome: value / total for outcome, value in implied.items()}


def _average_spread_market(bookmakers: list[dict[str, Any]], home_name: str) -> dict[str, float]:
    points: list[float] = []
    prices: list[float] = []
    for bookmaker in bookmakers:
        market = next((item for item in bookmaker.get("markets", []) if item.get("key") == "spreads"), None)
        for outcome in (market or {}).get("outcomes", []):
            if not _same_name(str(outcome.get("name", "")), home_name):
                continue
            try:
                points.append(float(outcome["point"]))
                prices.append(float(outcome["price"]))
            except (KeyError, TypeError, ValueError):
                continue
    if not points:
        return {}
    return {
        "spread_home_point": round(sum(points) / len(points), 3),
        "spread_home_price": round(sum(prices) / len(prices), 3),
        "spread_bookmakers": len(points),
    }


def _average_totals_market(bookmakers: list[dict[str, Any]]) -> dict[str, float]:
    points: list[float] = []
    over_prices: list[float] = []
    under_prices: list[float] = []
    for bookmaker in bookmakers:
        market = next((item for item in bookmaker.get("markets", []) if item.get("key") == "totals"), None)
        for outcome in (market or {}).get("outcomes", []):
            try:
                point = float(outcome["point"])
                price = float(outcome["price"])
            except (KeyError, TypeError, ValueError):
                continue
            points.append(point)
            if str(outcome.get("name", "")).lower() == "over":
                over_prices.append(price)
            elif str(outcome.get("name", "")).lower() == "under":
                under_prices.append(price)
    if not points:
        return {}
    return {
        "total_points": round(sum(points) / len(points), 3),
        "total_over_price": round(sum(over_prices) / len(over_prices), 3) if over_prices else 0.0,
        "total_under_price": round(sum(under_prices) / len(under_prices), 3) if under_prices else 0.0,
        "totals_bookmakers": max(len(over_prices), len(under_prices)),
    }


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
    return team_match_score(local_name, foreign_name)


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


def _fetch_text_with_status(url: str, cache_dir: Path, max_age_seconds: int) -> tuple[str, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{abs(hash(url))}.json"
    meta_path = cache_path.with_suffix(".meta.json")
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            metadata: dict[str, Any] = {}
            if meta_path.exists():
                try:
                    loaded = loads_json(meta_path.read_text(encoding="utf-8", errors="replace"))
                    metadata = loaded if isinstance(loaded, dict) else {}
                except json.JSONDecodeError:
                    metadata = {}
            return cache_path.read_text(encoding="utf-8", errors="replace"), {
                "source": "cache",
                "live_attempted": False,
                "credits_remaining": metadata.get("credits_remaining"),
                "credits_used": metadata.get("credits_used"),
                "credits_last": metadata.get("credits_last"),
            }
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        text = response.read().decode("utf-8", errors="replace")
        response_status = {
            "source": "live",
            "live_attempted": True,
            "credits_remaining": _header_int(response.headers, "x-requests-remaining"),
            "credits_used": _header_int(response.headers, "x-requests-used"),
            "credits_last": _header_int(response.headers, "x-requests-last"),
        }
    cache_path.write_text(text, encoding="utf-8")
    meta_path.write_text(json.dumps(response_status, ensure_ascii=False, indent=2), encoding="utf-8")
    return text, response_status


def _header_int(headers: Any, name: str) -> int | None:
    try:
        value = headers.get(name)
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _http_error_status(exc: urllib.error.HTTPError) -> dict[str, Any]:
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except OSError:
        pass
    payload: dict[str, Any] = {}
    if body:
        try:
            parsed = loads_json(body)
            payload = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    code = str(payload.get("error_code") or payload.get("code") or "").upper()
    provider_message = str(payload.get("message") or payload.get("error") or "").strip()
    if "OUT_OF_USAGE_CREDITS" in code or "CREDIT" in provider_message.upper():
        status = "out_of_credits"
        message = "The Odds API 额度已用完，本次已自动回退到新浪赔率。"
    elif exc.code in {401, 403} or "API_KEY" in code or "KEY" in provider_message.upper():
        status = "invalid_key"
        message = "The Odds API Key 无效或无权限，本次已自动回退到新浪赔率。"
    elif exc.code == 429:
        status = "rate_limited"
        message = "The Odds API 请求过于频繁，本次已自动回退到新浪赔率。"
    else:
        status = "http_error"
        message = provider_message or f"The Odds API 请求失败（HTTP {exc.code}）。"
    return {
        "source": "live",
        "live_attempted": True,
        "status": status,
        "message": message,
        "http_status": exc.code,
        "credits_remaining": _header_int(exc.headers, "x-requests-remaining"),
        "credits_used": _header_int(exc.headers, "x-requests-used"),
        "credits_last": _header_int(exc.headers, "x-requests-last"),
    }
