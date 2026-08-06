from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .collectors import RawMatch
from .http_utils import read_url_text
from .json_utils import loads_json
from .team_identity import TEAM_ALIASES


GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_MARKET_LIMIT = 500


@dataclass(frozen=True)
class PolymarketSignal:
    question: str
    probability_summary: str
    matched_market: str
    volume: float
    liquidity: float
    raw: dict[str, Any]


def fetch_polymarket_signals_for_matches(
    matches: list[RawMatch],
    cache_dir: str | Path,
    limit: int = DEFAULT_MARKET_LIMIT,
) -> dict[int, PolymarketSignal]:
    markets = _fetch_active_markets(Path(cache_dir) / "polymarket", limit=limit)
    result: dict[int, PolymarketSignal] = {}
    for match in matches:
        signal = _match_market_to_signal(match, markets)
        if signal:
            result[match.seq] = signal
    return result


def _fetch_active_markets(cache_dir: Path, limit: int) -> list[dict[str, Any]]:
    params = {
        "active": "true",
        "closed": "false",
        "limit": str(limit),
        "order": "volume24hr",
        "ascending": "false",
    }
    url = f"{GAMMA_API_BASE}/markets?{urllib.parse.urlencode(params)}"
    try:
        text = _fetch_text(url, cache_dir, max_age_seconds=600)
        data = loads_json(text)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _match_market_to_signal(match: RawMatch, markets: list[dict[str, Any]]) -> PolymarketSignal | None:
    best_market = None
    best_score = 0.0
    for market in markets:
        score = _market_match_score(match, market)
        if score > best_score:
            best_market = market
            best_score = score
    if not best_market or best_score < 1.8:
        return None

    outcomes = _json_list(best_market.get("outcomes"))
    prices = _float_list(best_market.get("outcomePrices"))
    summary = _probability_summary(outcomes, prices)
    if not summary:
        return None

    question = str(best_market.get("question") or best_market.get("title") or "").strip()
    slug = str(best_market.get("slug") or "").strip()
    return PolymarketSignal(
        question=question,
        probability_summary=summary,
        matched_market=slug or question,
        volume=_safe_float(best_market.get("volume") or best_market.get("volumeNum")),
        liquidity=_safe_float(best_market.get("liquidity") or best_market.get("liquidityNum")),
        raw={
            "id": best_market.get("id", ""),
            "slug": slug,
            "question": question,
            "outcomes": outcomes,
            "outcome_prices": prices,
            "volume": best_market.get("volume") or best_market.get("volumeNum") or "",
            "liquidity": best_market.get("liquidity") or best_market.get("liquidityNum") or "",
        },
    )


def _market_match_score(match: RawMatch, market: dict[str, Any]) -> float:
    text = _normalize_text(
        " ".join(
            str(market.get(key) or "")
            for key in ("question", "title", "slug", "description", "groupItemTitle")
        )
    )
    if not text or not _looks_like_soccer_market(text):
        return 0.0

    home_score = _team_score(match.home, text)
    away_score = _team_score(match.away, text)
    league_score = 0.25 if _normalize_text(match.league) and _normalize_text(match.league) in text else 0.0
    versus_bonus = 0.15 if home_score > 0 and away_score > 0 and re.search(r"\b(vs|v|versus|against)\b", text) else 0.0
    return home_score + away_score + league_score + versus_bonus


def _looks_like_soccer_market(text: str) -> bool:
    terms = (
        "soccer",
        "football",
        "premier league",
        "la liga",
        "bundesliga",
        "serie a",
        "ligue 1",
        "champions league",
        "europa league",
        "world cup",
        "club world cup",
        "mls",
    )
    return any(term in text for term in terms)


def _team_score(local_name: str, text: str) -> float:
    terms = [local_name, *TEAM_ALIASES.get(local_name, ())]
    best = 0.0
    for term in terms:
        normalized = _normalize_text(term)
        if not normalized:
            continue
        if re.search(rf"\b{re.escape(normalized)}\b", text):
            best = max(best, 1.0)
        elif normalized in text:
            best = max(best, 0.8)
    return best


def _probability_summary(outcomes: list[str], prices: list[float]) -> str:
    pairs = [(outcome.strip(), price) for outcome, price in zip(outcomes, prices) if outcome.strip() and 0 <= price <= 1]
    if not pairs:
        return ""
    pairs.sort(key=lambda item: item[1], reverse=True)
    return "，".join(f"{outcome} {price * 100:.0f}%" for outcome, price in pairs[:4])


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        raw = loads_json(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _float_list(value: Any) -> list[float]:
    result = []
    for item in _json_list(value):
        try:
            result.append(float(item))
        except ValueError:
            continue
    return result


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_text(value: str) -> str:
    value = value.lower().replace("-", " ")
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _fetch_text(url: str, cache_dir: Path, max_age_seconds: int) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            return cache_path.read_text(encoding="utf-8", errors="replace")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"})
    try:
        text = read_url_text(request, timeout=12)
    except (OSError, urllib.error.URLError):
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")
        raise
    cache_path.write_text(text, encoding="utf-8")
    return text
