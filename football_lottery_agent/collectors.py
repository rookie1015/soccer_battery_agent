from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .json_utils import loads_json
from .team_identity import TEAM_ALIASES as SHARED_TEAM_ALIASES


SINA_SFC_URL = "https://view.lottery.sina.com.cn/lottery_index/sfc/index?num="
SINA_GATEWAY_URL = "https://mix.lottery.sina.com.cn/gateway/index/entry"
SPORTTERY_FOOTBALL_MATCH_URL = "https://webapi.sporttery.cn/gateway/lottery/getFootBallMatchV1.qry"
SINA_COMMON_PARAMS = {"__caller__": "wap", "__verno__": "10000", "__version__": "1.0.0", "dpc": "1"}
MAINSTREAM_MEDIA_FEEDS = (
    ("espn", "ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news"),
    ("bbc_sport", "BBC Sport Football", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("sky_sports", "Sky Sports Football", "https://www.skysports.com/rss/11095"),
)
MEDIA_TEAM_ALIASES = {
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
    "曼城": ("manchester city", "man city"),
    "热刺": ("tottenham hotspur", "tottenham", "spurs"),
    "皇家社会": ("real sociedad",),
    "比利亚雷亚尔": ("villarreal",),
    "多特蒙德": ("borussia dortmund", "dortmund"),
    "法兰克福": ("eintracht frankfurt", "frankfurt"),
}
MEDIA_TEAM_ALIASES = {**SHARED_TEAM_ALIASES, **MEDIA_TEAM_ALIASES}


@dataclass(frozen=True)
class RawMatch:
    seq: int
    kickoff: str
    league: str
    home: str
    away: str
    home_recent: tuple[str, ...] = ()
    away_recent: tuple[str, ...] = ()
    match_id: str = ""


@dataclass(frozen=True)
class OddsRow:
    seq: int
    home: float
    draw: float
    away: float


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    published: str = ""


@dataclass(frozen=True)
class SinaDetail:
    odds: OddsRow | None
    injury_notes: tuple[str, ...]
    history_notes: tuple[str, ...]
    intelligence_notes: tuple[str, ...]
    raw: dict[str, Any]


def collect_issue(
    output_path: str | Path,
    issue: str | None = None,
    source: str = "sina",
    seed_path: str | Path | None = None,
    odds_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache",
    offline: bool = False,
    foreign_odds: bool = False,
    foreign_odds_requested: bool = False,
    foreign_odds_api_key: str | None = None,
    foreign_odds_regions: str = "uk,eu",
    foreign_odds_bookmakers: str = "",
    foreign_odds_sports: str = "",
    strength_model: bool = False,
    strength_team_ids: str | Path | None = None,
    strength_lookback: int = 20,
    strength_xg_matches: int = 8,
    skip_context_fetches: bool = False,
    skip_sina_details: bool = False,
    sina_odds_only: bool = False,
) -> Path:
    cache = Path(cache_dir)
    source_issue, raw_matches = load_matches(source=source, seed_path=seed_path, cache_dir=cache, issue=issue)
    issue_id = issue or source_issue or f"collected-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    metadata = {} if offline else fetch_sporttery_issue_metadata(issue_id, cache)
    odds_by_seq = load_odds_csv(odds_path) if odds_path else {}
    strength_by_seq = {}
    if strength_model and not offline:
        from .strength_model import build_strength_for_matches

        # Strength matching also learns conservative provider aliases. Run it
        # before media, foreign-odds and prediction-market matching so every
        # downstream source benefits in the same collection pass.
        strength_by_seq = build_strength_for_matches(
            raw_matches,
            cache_dir=cache,
            team_ids_path=strength_team_ids,
            lookback=strength_lookback,
            xg_matches=strength_xg_matches,
        )
    briefings = {} if skip_context_fetches else _fetch_briefings(raw_matches, cache, offline)
    media_briefings = {} if skip_context_fetches else _fetch_mainstream_media_briefings(raw_matches, cache, offline)
    if skip_sina_details:
        sina_details = {}
    elif sina_odds_only:
        sina_details = _fetch_sina_odds(raw_matches, cache, offline)
    else:
        sina_details = _fetch_sina_details(raw_matches, cache, offline)
    foreign_requested = foreign_odds_requested or foreign_odds
    foreign_odds_audit: dict[str, Any] = {
        "provider": "the_odds_api",
        "requested": foreign_requested,
        "configured": bool(foreign_odds_api_key),
        "status": "not_requested",
        "message": "简单分析未启用 The Odds API。",
        "queries_considered": 0,
        "attempted_queries": 0,
        "successful_queries": 0,
        "cache_hits": 0,
        "events_received": 0,
        "matched_matches": 0,
        "total_matches": len(raw_matches),
        "credits_remaining": None,
        "credits_used": None,
        "credits_last": None,
        "query_errors": [],
    }
    if foreign_requested and not foreign_odds_api_key:
        foreign_odds_audit.update(
            status="not_configured",
            message="完整分析未配置 The Odds API Key，本次未调用外盘，赔率自动使用新浪等现有来源。",
        )
    elif foreign_requested and offline:
        foreign_odds_audit.update(status="offline", message="离线模式未调用 The Odds API。")

    foreign_odds_by_seq = {}
    if foreign_odds and not offline:
        from .foreign_odds import fetch_foreign_odds_for_matches

        foreign_odds_by_seq = fetch_foreign_odds_for_matches(
            raw_matches,
            cache_dir=cache,
            api_key=foreign_odds_api_key,
            regions=foreign_odds_regions,
            bookmakers=foreign_odds_bookmakers,
            sport_keys=tuple(item.strip() for item in foreign_odds_sports.split(",") if item.strip()),
            audit=foreign_odds_audit,
        )
    polymarket_by_seq = {}
    if not skip_context_fetches and not offline:
        from .polymarket import fetch_polymarket_signals_for_matches

        polymarket_by_seq = fetch_polymarket_signals_for_matches(raw_matches, cache_dir=cache)
    matches: list[dict[str, Any]] = []
    for item in raw_matches:
        detail = sina_details.get(item.seq, SinaDetail(None, (), (), (), {}))
        briefing = briefings.get(item.seq, [])
        media_items = media_briefings.get(item.seq, [])
        news = [item for item in briefing if not _looks_like_injury(item.title)][:3]
        injury_news = [item for item in briefing if _looks_like_injury(item.title)][:3]
        history = [f"历史/战绩线索：{item.title}" for item in briefing if _looks_like_history(item.title)][:2]
        injury_notes = [f"伤停数据：{note}" for note in detail.injury_notes]
        history_notes = [f"历史交锋：{note}" for note in detail.history_notes]
        intelligence_notes = [f"情报：{note}" for note in detail.intelligence_notes]
        foreign = foreign_odds_by_seq.get(item.seq)
        foreign_notes = []
        if foreign:
            foreign_notes.append(
                f"外盘赔率：匹配 {foreign.matched_event}，{foreign.bookmaker_count} 家主流 bookmaker 均值 "
                f"{foreign.odds.home}/{foreign.odds.draw}/{foreign.odds.away}。"
            )
        elif foreign_odds:
            foreign_notes.append("外盘赔率：未匹配到国外 bookmaker 数据，保留国内/新浪赔率。")
        strength = strength_by_seq.get(item.seq)
        strength_notes = _strength_notes(strength) if strength else []
        polymarket = polymarket_by_seq.get(item.seq)
        polymarket_notes = _polymarket_notes(polymarket)
        media_notes = _mainstream_media_notes(media_items)
        has_real_odds = item.seq in odds_by_seq or foreign is not None or detail.odds is not None
        notes = _build_notes(item, news, injury_news, history + history_notes, has_odds=has_real_odds)
        notes[3:3] = injury_notes + intelligence_notes + media_notes + foreign_notes + polymarket_notes + strength_notes
        odds = odds_by_seq.get(item.seq) or (foreign.odds if foreign else None) or detail.odds or OddsRow(item.seq, 2.35, 3.15, 2.95)
        odds_source = "csv"
        if item.seq not in odds_by_seq:
            odds_source = "foreign_bookmakers" if foreign else ("sina_average_euro" if detail.odds else "default_placeholder")
        # Search snippets and media headlines are shown for context only. They
        # are not reliable enough to change probabilities through keyword hits.
        signals = infer_signals(item, [])
        # Strength establishes the statistical baseline first. Structured
        # pre-match intelligence is applied afterwards so it cannot be silently
        # overwritten when FotMob/SofaScore matched both teams.
        signals = _apply_strength_to_signals(signals, strength)
        signals = _apply_sina_detail_to_signals(signals, detail)
        strength_source = _strength_source(strength)
        selected_market = _selected_market_source(detail, foreign)
        collection_audit = _collection_audit(
            mode="full" if not skip_context_fetches else "simple",
            odds_source=odds_source,
            news=news,
            media_items=media_items,
            injury_news=injury_news,
            detail=detail,
            strength_source=strength_source,
            polymarket=polymarket,
            market_source=selected_market,
        )

        matches.append(
            {
                "seq": item.seq,
                "kickoff": item.kickoff,
                "league": item.league,
                "home": item.home,
                "away": item.away,
                "odds": {"home": odds.home, "draw": odds.draw, "away": odds.away},
                "signals": signals,
                "notes": notes,
                "sources": {
                    "schedule": {"provider": source, "match_id": item.match_id},
                    "news": [news_item.__dict__ for news_item in news],
                    "mainstream_media": [news_item.__dict__ for news_item in media_items],
                    "injuries": [news_item.__dict__ for news_item in injury_news],
                    "history": history,
                    "sina_detail": detail.raw,
                    "foreign_odds": foreign.raw if foreign else {},
                    "odds_market": selected_market,
                    "polymarket": polymarket.raw if polymarket else {},
                    "strength_model": strength_source,
                    "collection_audit": collection_audit,
                    "data_usage": _data_usage_summary(collection_audit, foreign is not None),
                    "odds": odds_source,
                },
            }
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        **metadata,
        "analysis_mode": "full" if not skip_context_fetches else "simple",
        "foreign_odds_audit": foreign_odds_audit,
        "snapshot_collected_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_schema_version": "1",
    }
    output.write_text(
        json.dumps({"issue": issue_id, "metadata": metadata, "matches": matches}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def fetch_sporttery_issue_metadata(issue: str, cache_dir: str | Path = "data/cache") -> dict[str, str]:
    cache = Path(cache_dir)
    for sell_status in ("0", "1", "3"):
        params = {
            "param": "90,0",
            "lotteryDrawNum": issue,
            "sellStatus": sell_status,
            "termLimits": "10",
        }
        url = f"{SPORTTERY_FOOTBALL_MATCH_URL}?{urllib.parse.urlencode(params)}"
        try:
            raw = loads_json(_fetch_text(url, cache, max_age_seconds=300))
        except (urllib.error.URLError, ValueError):
            continue
        if str(raw.get("errorCode")) != "0":
            continue
        value = raw.get("value") or {}
        sfc_match = value.get("sfcMatch") or {}
        if str(sfc_match.get("lotteryDrawNum") or "").strip() != issue:
            continue
        sale_end_time = str(sfc_match.get("lotterySaleEndtime") or "").strip()
        if not sale_end_time:
            continue
        metadata = {
            "purchase_deadline": sale_end_time,
            "purchase_deadline_source": "中国体彩网官方",
        }
        sale_begin_time = str(sfc_match.get("lotterySaleBegintime") or "").strip()
        if sale_begin_time:
            metadata["sale_begin_time"] = sale_begin_time
        return metadata
    return {}


def _fetch_briefings(raw_matches: list[RawMatch], cache: Path, offline: bool) -> dict[int, list[NewsItem]]:
    if offline:
        return {match.seq: [] for match in raw_matches}
    with ThreadPoolExecutor(max_workers=6) as executor:
        pairs = executor.map(lambda match: (match.seq, fetch_match_briefing(match, cache)), raw_matches)
    return dict(pairs)


def _fetch_mainstream_media_briefings(raw_matches: list[RawMatch], cache: Path, offline: bool) -> dict[int, list[NewsItem]]:
    if offline:
        return {match.seq: [] for match in raw_matches}
    feed_items = _fetch_mainstream_feed_items(cache)
    with ThreadPoolExecutor(max_workers=6) as executor:
        pairs = executor.map(lambda match: (match.seq, fetch_mainstream_media_news(match, cache, feed_items)), raw_matches)
    return dict(pairs)


def _fetch_sina_details(raw_matches: list[RawMatch], cache: Path, offline: bool) -> dict[int, SinaDetail]:
    if offline:
        return {match.seq: SinaDetail(None, (), (), (), {}) for match in raw_matches}
    with ThreadPoolExecutor(max_workers=6) as executor:
        pairs = executor.map(lambda match: (match.seq, fetch_sina_detail(match, cache)), raw_matches)
    return dict(pairs)


def _fetch_sina_odds(raw_matches: list[RawMatch], cache: Path, offline: bool) -> dict[int, SinaDetail]:
    if offline:
        return {match.seq: SinaDetail(None, (), (), (), {}) for match in raw_matches}
    with ThreadPoolExecutor(max_workers=6) as executor:
        pairs = executor.map(lambda match: (match.seq, fetch_sina_odds_detail(match, cache)), raw_matches)
    return dict(pairs)


def load_matches(
    source: str,
    seed_path: str | Path | None,
    cache_dir: Path,
    issue: str | None = None,
) -> tuple[str, list[RawMatch]]:
    if seed_path:
        return "", load_seed_matches(seed_path)
    if source == "sina":
        return fetch_sina_sfc(cache_dir, issue=issue)
    raise ValueError("Unsupported source. Use 'sina' or pass --seed.")


def load_seed_matches(path: str | Path) -> list[RawMatch]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    matches = [
        RawMatch(
            seq=int(row["seq"]),
            kickoff=row["kickoff"].strip(),
            league=row["league"].strip(),
            home=row["home"].strip(),
            away=row["away"].strip(),
        )
        for row in rows
    ]
    _require_14(matches)
    return matches


def load_odds_csv(path: str | Path) -> dict[int, OddsRow]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return {
        int(row["seq"]): OddsRow(
            seq=int(row["seq"]),
            home=float(row["home"]),
            draw=float(row["draw"]),
            away=float(row["away"]),
        )
        for row in rows
    }


def fetch_sina_sfc(
    cache_dir: Path,
    url: str = SINA_SFC_URL,
    issue: str | None = None,
) -> tuple[str, list[RawMatch]]:
    if issue:
        url = f"{url}{urllib.parse.quote(issue)}"
    html = _fetch_text(url, cache_dir, max_age_seconds=900)
    source_issue = _first_match(r'name="num"\s+value="(\d+)"', html) or _first_match(r'<option value="(\d+)"[^>]*selected', html)
    if issue and source_issue and source_issue != issue:
        raise ValueError(f"Sina returned issue {source_issue} when issue {issue} was requested.")
    table = _first_match(r'(<table class="sfcPubTable">[\s\S]*?</table>)', html)
    if not table:
        raise ValueError("Sina SFC table not found.")
    table_issues = set(re.findall(r'name="(\d{5})(?:0[1-9]|1[0-4])\[\d+\]"', table))
    if len(table_issues) > 1:
        raise ValueError(f"Sina table contains mixed issue ids: {', '.join(sorted(table_issues))}.")
    table_issue = next(iter(table_issues), None)
    expected_issue = issue or source_issue
    if expected_issue and table_issue and table_issue != expected_issue:
        raise ValueError(
            f"Sina table belongs to issue {table_issue}, but issue {expected_issue} was requested. "
            "Existing issue data was not overwritten."
        )

    year = datetime.now().year
    rows = re.findall(r"<tr[^>]*>[\s\S]*?</tr>", table)
    matches: list[RawMatch] = []
    for row in rows:
        cells = _extract_cells(row)
        if len(cells) < 6 or not cells[0].strip().isdigit():
            continue
        matches.append(
            RawMatch(
                seq=int(cells[0]),
                league=cells[1],
                kickoff=_normalize_sina_time(cells[2], year),
                home=_clean_team_name(cells[3]),
                away=_clean_team_name(cells[5]),
                home_recent=_extract_recent(row, "zd"),
                away_recent=_extract_recent(row, "kd"),
                match_id=_first_match(r"matchId=(\d+)", row),
            )
        )
    _require_14(matches)
    return source_issue, matches


def fetch_match_news(match: RawMatch, cache_dir: Path, limit: int = 3) -> list[NewsItem]:
    return _fetch_bing_news(f"{match.home} {match.away} {match.league} 赛前 新闻", cache_dir, limit)


def fetch_injury_news(match: RawMatch, cache_dir: Path, limit: int = 3) -> list[NewsItem]:
    return _fetch_bing_news(f"{match.home} {match.away} 伤停 停赛 首发 阵容", cache_dir, limit)


def fetch_history_notes(match: RawMatch, cache_dir: Path) -> list[str]:
    items = _fetch_bing_news(f"{match.home} {match.away} 历史交锋 战绩", cache_dir, 2)
    return [f"历史战绩线索：{item.title}" for item in items]


def fetch_match_briefing(match: RawMatch, cache_dir: Path, limit: int = 5) -> list[NewsItem]:
    home_term = _primary_media_term(match.home)
    away_term = _primary_media_term(match.away)
    query = f'"{home_term}" "{away_term}" football preview injuries lineup'
    items = search_web_news(query, cache_dir, limit * 2)
    matched = [item for item in items if _news_item_matches_both_teams(match, item)]
    if matched or (home_term == match.home and away_term == match.away):
        return _dedupe_news_items(matched)[:limit]

    chinese_query = f"{match.home} {match.away} {match.league} 赛前 伤停 首发 阵容"
    chinese_items = search_web_news(chinese_query, cache_dir, limit)
    matched.extend(item for item in chinese_items if _news_item_matches_both_teams(match, item))
    return _dedupe_news_items(matched)[:limit]


def fetch_mainstream_media_news(
    match: RawMatch,
    cache_dir: Path,
    feed_items: list[NewsItem] | None = None,
    limit: int = 4,
) -> list[NewsItem]:
    items = list(feed_items if feed_items is not None else _fetch_mainstream_feed_items(cache_dir))
    matched = [item for item in items if _media_item_matches_match(match, item)]
    if len(matched) < limit:
        matched.extend(_fetch_the_athletic_public_items(match, cache_dir, limit - len(matched)))
    return _dedupe_news_items(matched)[:limit]


def fetch_sina_detail(match: RawMatch, cache_dir: Path) -> SinaDetail:
    if not match.match_id:
        return SinaDetail(None, (), (), (), {"fetch_status": "missing_match_id"})
    raw_odds, odds_status = _sina_gateway_result("footballMatchOddsEuro", {"matchId": match.match_id}, cache_dir)
    raw_asian, asian_status = _sina_gateway_result("footballMatchOddsAsia", {"matchId": match.match_id}, cache_dir)
    raw_injury, injury_status = _sina_gateway_result("footballMatchTeamInjury", {"matchId": match.match_id}, cache_dir)
    raw_intelligence, intelligence_status = _sina_gateway_result("FootballMatchIntelligence", {"matchId": match.match_id}, cache_dir)
    raw_history, history_status = _sina_gateway_result(
        "footballMatchTeamBattleHistory",
        {"matchId": match.match_id, "limit": "10", "isSameHostAway": "0", "isSameLeague": "0"},
        cache_dir,
    )
    odds = _average_sina_euro_odds(match.seq, raw_odds)
    injury_notes = tuple(_format_injury_notes(raw_injury, match))
    history_notes = tuple(_format_history_notes(raw_history, match))
    intelligence_notes = tuple(_format_intelligence_notes(raw_intelligence, match))
    raw = {
        "odds_rows": _safe_len(raw_odds),
        "odds_fetch_status": odds_status,
        **_odds_market_summary(raw_odds),
        "asian_rows": _safe_len(raw_asian),
        "asian_fetch_status": asian_status,
        **_asian_market_summary(raw_asian),
        "injury_team1": _safe_len(_data(raw_injury).get("team1", []) if isinstance(_data(raw_injury), dict) else []),
        "injury_team2": _safe_len(_data(raw_injury).get("team2", []) if isinstance(_data(raw_injury), dict) else []),
        "injury_fetch_status": injury_status,
        **_injury_signal_summary(raw_injury),
        "intelligence_rows": _safe_len(intelligence_notes),
        "intelligence_fetch_status": intelligence_status,
        **_intelligence_signal_summary(raw_intelligence),
        "history_rows": _safe_len(raw_history),
        "history_fetch_status": history_status,
        **_history_signal_summary(raw_history),
    }
    return SinaDetail(
        odds=odds,
        injury_notes=injury_notes,
        history_notes=history_notes,
        intelligence_notes=intelligence_notes,
        raw=raw,
    )


def fetch_sina_odds_detail(match: RawMatch, cache_dir: Path) -> SinaDetail:
    if not match.match_id:
        return SinaDetail(None, (), (), (), {"fetch_status": "missing_match_id", "mode": "odds_only"})
    raw_odds, odds_status = _sina_gateway_result("footballMatchOddsEuro", {"matchId": match.match_id}, cache_dir)
    odds = _average_sina_euro_odds(match.seq, raw_odds)
    return SinaDetail(
        odds=odds,
        injury_notes=(),
        history_notes=(),
        intelligence_notes=(),
        raw={
            "odds_rows": _safe_len(raw_odds),
            "odds_fetch_status": odds_status,
            **_odds_market_summary(raw_odds),
            "mode": "odds_only",
        },
    )


def _sina_gateway(cat1: str, params: dict[str, str], cache_dir: Path) -> Any:
    return _sina_gateway_result(cat1, params, cache_dir)[0]


def _sina_gateway_result(cat1: str, params: dict[str, str], cache_dir: Path) -> tuple[Any, str]:
    query = {**SINA_COMMON_PARAMS, "cat1": cat1, **params}
    url = f"{SINA_GATEWAY_URL}?{urllib.parse.urlencode(query)}"
    try:
        text = _fetch_text(url, cache_dir, max_age_seconds=900)
        payload = loads_json(text)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return [], "request_failed"
    result = payload.get("result", {})
    status = result.get("status", {})
    if status.get("code") != 0:
        return [], "provider_error"
    data = result.get("data", [])
    return data, "available" if _safe_len(data) else "confirmed_empty"


def infer_signals(match: RawMatch, notes: list[str]) -> dict[str, float]:
    home_form = _recent_form_score(match.home_recent)
    away_form = _recent_form_score(match.away_recent)
    text = " ".join(notes)
    injury = _keyword_score(text, ["伤停", "停赛", "缺阵", "伤病", "伤缺"])
    pressure = _keyword_score(text, ["轮换", "赛程密集", "一周双赛", "体能"])
    motivation = _keyword_score(text, ["争冠", "争四", "保级", "出线", "晋级", "德比"])

    return {
        "home_form": home_form,
        "away_form": away_form,
        "home_motivation": min(0.78, 0.50 + motivation * 0.18),
        "away_motivation": min(0.78, 0.50 + motivation * 0.18),
        "home_injury_impact": max(_keyword_score(text, [f"{match.home} 伤", f"{match.home} 缺阵"]), injury * 0.35),
        "away_injury_impact": max(_keyword_score(text, [f"{match.away} 伤", f"{match.away} 缺阵"]), injury * 0.35),
        "schedule_pressure_home": pressure * 0.5,
        "schedule_pressure_away": pressure * 0.5,
    }


def _apply_sina_detail_to_signals(signals: dict[str, float], detail: SinaDetail) -> dict[str, float]:
    """Apply side-aware structured Sina evidence in full analysis.

    The old keyword pass combined both teams' notes and often assigned the same
    injury or motivation value to both sides. Structured counts and good/bad
    importance retain which team the evidence belongs to.
    """
    raw = detail.raw if isinstance(detail.raw, dict) else {}
    if raw.get("mode") == "odds_only":
        return signals
    updated = dict(signals)
    home_injuries = float(raw.get("injury_team1_weight") or raw.get("injury_team1") or 0)
    away_injuries = float(raw.get("injury_team2_weight") or raw.get("injury_team2") or 0)
    if home_injuries or away_injuries or raw.get("injury_fetch_status") == "confirmed_empty":
        updated["home_injury_impact"] = min(0.45, home_injuries * 0.05)
        updated["away_injury_impact"] = min(0.45, away_injuries * 0.05)
    for side, prefix in (("home", "team1"), ("away", "team2")):
        good = float(raw.get(f"intelligence_{prefix}_good") or 0.0)
        bad = float(raw.get(f"intelligence_{prefix}_bad") or 0.0)
        total = good + bad
        if total <= 0:
            continue
        evidence_edge = (good - bad) / total
        updated[f"{side}_form"] = _clamp_signal(updated[f"{side}_form"] + evidence_edge * 0.08)
        updated[f"{side}_motivation"] = _clamp_signal(updated[f"{side}_motivation"] + evidence_edge * 0.04)
    return updated


def _injury_signal_summary(raw: Any) -> dict[str, float]:
    data = _data(raw)
    if not isinstance(data, dict):
        return {}
    result: dict[str, float] = {}
    for prefix in ("team1", "team2"):
        players = data.get(prefix) or []
        result[f"injury_{prefix}_weight"] = round(
            sum(_injury_player_weight(player) for player in players if isinstance(player, dict)),
            3,
        )
    return result


def _injury_player_weight(player: dict[str, Any]) -> float:
    position = str(player.get("positionCn") or player.get("position") or "").lower()
    reason = str(player.get("reason") or "").lower()
    weight = 1.0
    if any(term in position for term in ("门将", "goalkeeper", "keeper")):
        weight = 1.30
    elif any(term in position for term in ("前锋", "中锋", "forward", "striker")):
        weight = 1.18
    elif any(term in position for term in ("中场", "midfield")):
        weight = 1.12
    elif any(term in position for term in ("后卫", "defender", "back")):
        weight = 1.08
    if any(term in reason for term in ("停赛", "suspension", "赛季报销", "长期")):
        weight *= 1.12
    return min(1.6, weight)


def _intelligence_signal_summary(raw: Any) -> dict[str, float]:
    data = _data(raw)
    if not isinstance(data, dict):
        return {}
    result: dict[str, float] = {}
    for prefix in ("team1", "team2"):
        section = data.get(prefix) or {}
        if not isinstance(section, dict):
            continue
        for tone in ("good", "bad"):
            result[f"intelligence_{prefix}_{tone}"] = round(
                sum(_importance(item) for item in section.get(tone) or []),
                3,
            )
    return result


def _importance(value: Any) -> float:
    if not isinstance(value, dict):
        return 1.0
    try:
        return min(5.0, max(1.0, float(value.get("importance") or 1.0)))
    except (TypeError, ValueError):
        return 1.0


def _history_signal_summary(raw: Any) -> dict[str, float | int]:
    if not isinstance(raw, list):
        return {}
    outcomes = []
    for row in raw[:10]:
        try:
            outcomes.append(float(row.get("score1")) == float(row.get("score2")))
        except (AttributeError, TypeError, ValueError):
            continue
    if not outcomes:
        return {}
    return {
        "history_matches": len(outcomes),
        "history_draw_rate": round(sum(outcomes) / len(outcomes), 3),
    }


def _average_sina_euro_odds(seq: int, rows: Any) -> OddsRow | None:
    if not isinstance(rows, list):
        return None
    values: list[tuple[float, float, float]] = []
    for row in rows:
        try:
            values.append((float(row["o1New"]), float(row["o2New"]), float(row["o3New"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not values:
        return None
    home = sum(item[0] for item in values) / len(values)
    draw = sum(item[1] for item in values) / len(values)
    away = sum(item[2] for item in values) / len(values)
    return OddsRow(seq=seq, home=round(home, 3), draw=round(draw, 3), away=round(away, 3))


def _odds_market_summary(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    current: list[dict[str, float]] = []
    opening: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current_probability = _normalized_odds_row(row, ("o1New", "o2New", "o3New"))
        opening_probability = _normalized_odds_row(row, ("o1Ini", "o2Ini", "o3Ini"))
        if current_probability:
            current.append(current_probability)
        if opening_probability:
            opening.append(opening_probability)
    if not current:
        return {}
    consensus = _average_probability_rows(current)
    result: dict[str, Any] = {
        "market_consensus": consensus,
        "market_bookmakers": len(current),
        "market_dispersion": {
            outcome: round(max(row[outcome] for row in current) - min(row[outcome] for row in current), 4)
            for outcome in ("3", "1", "0")
        },
    }
    if opening:
        opening_consensus = _average_probability_rows(opening)
        result["market_opening_consensus"] = opening_consensus
        result["market_movement"] = {
            outcome: round(consensus[outcome] - opening_consensus[outcome], 4)
            for outcome in ("3", "1", "0")
        }
    return result


def _asian_market_summary(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    opening_lines: list[float] = []
    current_lines: list[float] = []
    price_edges: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            opening_lines.append(float(row["o3Ini"]))
            current_lines.append(float(row["o3New"]))
            home_price = float(row["o1New"])
            away_price = float(row["o2New"])
        except (KeyError, TypeError, ValueError):
            continue
        price_edges.append(max(-0.25, min(0.25, (away_price - home_price) / 2.0)))
    if not current_lines:
        return {}
    current = sum(current_lines) / len(current_lines)
    opening = sum(opening_lines) / len(opening_lines) if opening_lines else current
    return {
        "asian_current_line": round(current, 3),
        "asian_opening_line": round(opening, 3),
        "asian_line_movement": round(current - opening, 3),
        "asian_home_price_edge": round(sum(price_edges) / len(price_edges), 4) if price_edges else 0.0,
    }


def _normalized_odds_row(row: dict[str, Any], keys: tuple[str, str, str]) -> dict[str, float] | None:
    try:
        values = [float(row[key]) for key in keys]
    except (KeyError, TypeError, ValueError):
        return None
    if any(value <= 1.0 for value in values):
        return None
    implied = [1.0 / value for value in values]
    total = sum(implied)
    return {
        outcome: implied[index] / total
        for index, outcome in enumerate(("3", "1", "0"))
    }


def _average_probability_rows(rows: list[dict[str, float]]) -> dict[str, float]:
    return {
        outcome: round(sum(row[outcome] for row in rows) / len(rows), 6)
        for outcome in ("3", "1", "0")
    }


def _format_injury_notes(raw: Any, match: RawMatch) -> list[str]:
    data = _data(raw)
    if not isinstance(data, dict):
        return []
    notes = []
    for label, key in [(match.home, "team1"), (match.away, "team2")]:
        players = data.get(key) or []
        for player in players[:4]:
            name = player.get("playerCn") or player.get("name") or "未知球员"
            position = player.get("positionCn") or "-"
            reason = player.get("reason") or "受伤"
            notes.append(f"{label} {name}（{position}，{reason}）")
    return notes


def _format_history_notes(raw: Any, match: RawMatch) -> list[str]:
    if not isinstance(raw, list):
        return []
    notes = []
    for row in raw[:3]:
        league = row.get("league", "")
        date = str(row.get("matchTimeFormat", ""))[:10]
        team1 = row.get("team1", "")
        team2 = row.get("team2", "")
        score1 = row.get("score1", "-")
        score2 = row.get("score2", "-")
        notes.append(f"{date} {league} {team1} {score1}-{score2} {team2}")
    return notes


def _format_intelligence_notes(raw: Any, match: RawMatch) -> list[str]:
    data = _data(raw)
    if not isinstance(data, dict):
        return []
    notes = []
    for label, key in [(match.home, "team1"), ("中立", "neutral"), (match.away, "team2")]:
        section = data.get(key) or {}
        if isinstance(section, list):
            entries = section
            for item in entries[:2]:
                content = item.get("content") if isinstance(item, dict) else str(item)
                if content:
                    notes.append(f"{label}：{content}")
            continue
        for tone in ("good", "bad"):
            for item in (section.get(tone) or [])[:2]:
                content = item.get("content", "")
                if content:
                    prefix = "利好" if tone == "good" else "不利"
                    notes.append(f"{label}{prefix}：{content}")
    return notes[:8]


def _fetch_mainstream_feed_items(cache_dir: Path) -> list[NewsItem]:
    items: list[NewsItem] = []
    media_cache = cache_dir / "mainstream_media"
    for _key, source, url in MAINSTREAM_MEDIA_FEEDS:
        try:
            xml_text = _fetch_text(url, media_cache, max_age_seconds=1800)
        except (OSError, urllib.error.URLError):
            continue
        for item in _parse_rss(xml_text):
            items.append(NewsItem(title=f"{source}：{item.title}", link=item.link, published=item.published))
    return _dedupe_news_items(items)


def _fetch_the_athletic_public_items(match: RawMatch, cache_dir: Path, limit: int) -> list[NewsItem]:
    if limit <= 0:
        return []
    home_term = _primary_media_term(match.home)
    away_term = _primary_media_term(match.away)
    query = f"site:theathletic.com {home_term} {away_term} {match.league} football soccer"
    items = _fetch_duckduckgo_results(query, cache_dir / "mainstream_media", limit)
    return [
        NewsItem(title=f"The Athletic：{item.title}", link=item.link, published=item.published)
        for item in items
        if "theathletic.com" in item.link.lower() or "the athletic" in item.title.lower()
    ][:limit]


def _media_item_matches_match(match: RawMatch, item: NewsItem) -> bool:
    text = _normalize_media_text(f"{item.title} {item.link}")
    home_hit = any(term in text for term in _media_terms(match.home))
    away_hit = any(term in text for term in _media_terms(match.away))
    league_hit = _normalize_media_text(match.league) in text or any(term in text for term in ("world cup", "football", "soccer"))
    return (home_hit and away_hit) or ((home_hit or away_hit) and league_hit)


def _news_item_matches_both_teams(match: RawMatch, item: NewsItem) -> bool:
    text = _normalize_media_text(f"{item.title} {item.link}")
    return (
        any(term in text for term in _media_terms(match.home))
        and any(term in text for term in _media_terms(match.away))
    )


def _media_terms(team: str) -> tuple[str, ...]:
    terms = [team, *SHARED_TEAM_ALIASES.get(team, ()), *MEDIA_TEAM_ALIASES.get(team, ())]
    normalized = []
    for term in terms:
        value = _normalize_media_text(term)
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _primary_media_term(team: str) -> str:
    aliases = SHARED_TEAM_ALIASES.get(team) or MEDIA_TEAM_ALIASES.get(team)
    return aliases[0] if aliases else team


def _normalize_media_text(value: str) -> str:
    value = unescape(value).lower()
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_news_items(items: list[NewsItem]) -> list[NewsItem]:
    seen = set()
    result = []
    for item in items:
        key = (item.title.lower(), item.link.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _mainstream_media_notes(items: list[NewsItem]) -> list[str]:
    return [f"主流媒体：{item.title}" for item in items[:4]]


def _fetch_bing_news(query: str, cache_dir: Path, limit: int) -> list[NewsItem]:
    gdelt_items = _fetch_gdelt_news(query, cache_dir, limit)
    if gdelt_items:
        return gdelt_items
    duck_items = _fetch_duckduckgo_results(query, cache_dir, limit)
    if duck_items:
        return duck_items
    return []


def search_web_news(query: str, cache_dir: str | Path, limit: int = 5) -> list[NewsItem]:
    """Search indexed news with the project's GDELT-first, DuckDuckGo fallback flow."""
    root = Path(cache_dir)
    items = _fetch_bing_news(query, root, limit)
    if items:
        return items
    return _fetch_google_news(query, root, limit)


def _fetch_google_news(query: str, cache_dir: Path, limit: int) -> list[NewsItem]:
    url = f"https://news.google.com/rss/search?{urllib.parse.urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"
    try:
        return _parse_rss(_fetch_text(url, cache_dir, max_age_seconds=3600))[:limit]
    except (OSError, urllib.error.URLError, ET.ParseError):
        return []


def _fetch_gdelt_news(query: str, cache_dir: Path, limit: int) -> list[NewsItem]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(limit),
        "sort": "HybridRel",
    }
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urllib.parse.urlencode(params)}"
    try:
        raw = _fetch_text(url, cache_dir, max_age_seconds=3600)
        data = loads_json(raw)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    items = []
    for article in data.get("articles", [])[:limit]:
        title = _squash(str(article.get("title", "")))
        link = str(article.get("url", ""))
        published = str(article.get("seendate", ""))
        if title:
            items.append(NewsItem(title=title, link=link, published=published))
    return items


def _fetch_duckduckgo_results(query: str, cache_dir: Path, limit: int) -> list[NewsItem]:
    url = f"https://duckduckgo.com/html/?{urllib.parse.urlencode({'q': query})}"
    try:
        html = _fetch_text(url, cache_dir, max_age_seconds=3600)
    except (OSError, urllib.error.URLError):
        return []

    items: list[NewsItem] = []
    for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', html):
        link = _decode_duckduckgo_url(match.group(1))
        title = _squash(re.sub(r"<[^>]+>", " ", match.group(2)))
        if title:
            items.append(NewsItem(title=title, link=link))
        if len(items) >= limit:
            break
    return items


def _fetch_text(url: str, cache_dir: Path, max_age_seconds: int) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.txt"
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            return cache_path.read_text(encoding="utf-8", errors="replace")
    headers = {"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"}
    if "webapi.sporttery.cn" in url:
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.sporttery.cn/ctzc/jsq/index.html",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")
        raise exc
    cache_path.write_text(text, encoding="utf-8")
    return text


def _parse_rss(xml_text: str) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = _node_text(node, "title")
        link = _node_text(node, "link")
        published = _node_text(node, "pubDate")
        if title:
            items.append(NewsItem(title=_squash(title), link=link, published=published))
    return items


def _build_notes(match: RawMatch, news: list[NewsItem], injury_news: list[NewsItem], history: list[str], has_odds: bool) -> list[str]:
    notes = [
        f"赛程源：{match.league}，{match.home} vs {match.away}。",
        f"近期状态：{match.home} {''.join(match.home_recent) or '暂无'}，{match.away} {''.join(match.away_recent) or '暂无'}。",
    ]
    if not has_odds:
        notes.append("赔率暂用默认占位值，建议补充 odds.csv 后再作为正式参考。")
    notes.extend(f"新闻线索：{item.title}" for item in news)
    notes.extend(f"伤停线索：{item.title}" for item in injury_news)
    notes.extend(history)
    return notes[:12]


def _extract_cells(row_html: str) -> list[str]:
    parser = _CellTextParser()
    parser.feed(row_html)
    return [_squash(cell) for cell in parser.cells]


class _CellTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._in_cell = False
        self._current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"td", "th"}:
            self._in_cell = True
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self.cells.append(" ".join(self._current))
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current.append(data)


def _extract_recent(row_html: str, team_class: str) -> tuple[str, ...]:
    m = re.search(rf'<span class="{team_class}"[\s\S]*?</span>([\s\S]*?)</td>', row_html)
    if not m:
        return ()
    return tuple(re.findall(r">([WDL])<", m.group(1)))[:5]


def _normalize_sina_time(value: str, year: int) -> str:
    m = re.search(r"(\d{2})-(\d{2})\s+(\d{2}:\d{2})", value)
    if not m:
        return datetime.now().astimezone().isoformat(timespec="minutes")
    return f"{year}-{m.group(1)}-{m.group(2)}T{m.group(3)}:00+08:00"


def _clean_team_name(value: str) -> str:
    return re.sub(r"\s*[WDL](\s+[WDL])*\s*$", "", value).strip()


def _recent_form_score(recent: tuple[str, ...]) -> float:
    if not recent:
        return 0.5
    score = sum({"W": 1.0, "D": 0.5, "L": 0.0}.get(item, 0.5) for item in recent) / len(recent)
    return round(0.25 + score * 0.5, 3)


def _node_text(node: ET.Element, child_name: str) -> str:
    child = node.find(child_name)
    return "" if child is None or child.text is None else child.text.strip()


def _decode_duckduckgo_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return value


def _looks_like_injury(text: str) -> bool:
    return any(keyword in text for keyword in ["伤停", "停赛", "缺阵", "伤病", "首发", "阵容"])


def _looks_like_history(text: str) -> bool:
    return any(keyword in text for keyword in ["历史", "交锋", "战绩", "往绩", "纪录"])


def _strength_notes(strength: Any) -> list[str]:
    notes = []
    if getattr(strength, "home", None):
        notes.extend(f"实力模型：{note}" for note in strength.home.notes)
    if getattr(strength, "away", None):
        notes.extend(f"实力模型：{note}" for note in strength.away.notes)
    home_rating = getattr(getattr(strength, "home", None), "rating", None)
    away_rating = getattr(getattr(strength, "away", None), "rating", None)
    if home_rating is not None and away_rating is not None:
        edge = home_rating - away_rating
        notes.append(f"实力模型：综合评分主队 {home_rating:.3f} / 客队 {away_rating:.3f}，差值 {edge:+.3f}。")
    for squad in (getattr(strength, "home_squad", None), getattr(strength, "away_squad", None)):
        if not squad:
            continue
        absence_text = f"，缺阵 {', '.join(squad.notable_absences)}" if squad.notable_absences else ""
        form_text = (
            f"，主力近期评分 {squad.recent_form_rating:.2f}（{squad.recent_form_samples} 人次）"
            if squad.recent_form_rating is not None and squad.recent_form_samples >= 3
            else ""
        )
        notes.append(
            f"阵容模型：{squad.team.name} 估算主力11人身价约 €{squad.estimated_starting_value:.0f}m，"
            f"可用度扣减 {squad.availability_penalty:.0%}{form_text}{absence_text}。"
        )
    if not notes:
        notes.append("实力模型：FotMob/SofaScore 未匹配到球队或近期样本不足。")
    return notes[:8]


def _polymarket_notes(signal: Any) -> list[str]:
    if not signal:
        return []
    volume = getattr(signal, "volume", 0.0)
    volume_text = f"，成交量约 ${volume:,.0f}" if volume else ""
    question = getattr(signal, "question", "")
    summary = getattr(signal, "probability_summary", "")
    if not question or not summary:
        return []
    return [f"Polymarket预测市场：{question}；市场概率 {summary}{volume_text}。"]


def _strength_source(strength: Any) -> dict[str, Any]:
    if not strength:
        return {}
    home = getattr(strength, "home", None)
    away = getattr(strength, "away", None)
    home_squad = getattr(strength, "home_squad", None)
    away_squad = getattr(strength, "away_squad", None)
    status = "complete" if home is not None and away is not None else "partial" if home is not None or away is not None else "unmatched"
    return {
        **getattr(strength, "source", {}),
        "status": status,
        "home_rating": getattr(home, "rating", None),
        "away_rating": getattr(away, "rating", None),
        "home_draw_rate": getattr(home, "draw_rate", None),
        "away_draw_rate": getattr(away, "draw_rate", None),
        "home_matches_used": getattr(home, "matches_used", None),
        "away_matches_used": getattr(away, "matches_used", None),
        "home_xg_matches": getattr(home, "xg_matches_used", None),
        "away_xg_matches": getattr(away, "xg_matches_used", None),
        "home_xg_provider": getattr(home, "xg_provider", None),
        "away_xg_provider": getattr(away, "xg_provider", None),
        "home_xg_for": getattr(home, "xg_for_per_match", None),
        "home_xg_against": getattr(home, "xg_against_per_match", None),
        "away_xg_for": getattr(away, "xg_for_per_match", None),
        "away_xg_against": getattr(away, "xg_against_per_match", None),
        "home_goals_for": getattr(home, "goals_for_per_match", None),
        "home_goals_against": getattr(home, "goals_against_per_match", None),
        "away_goals_for": getattr(away, "goals_for_per_match", None),
        "away_goals_against": getattr(away, "goals_against_per_match", None),
        "home_squad_paper_rating": getattr(home_squad, "paper_rating", None),
        "away_squad_paper_rating": getattr(away_squad, "paper_rating", None),
        "home_squad_current_rating": getattr(home_squad, "current_rating", None),
        "away_squad_current_rating": getattr(away_squad, "current_rating", None),
        "home_squad_recent_form_rating": getattr(home_squad, "recent_form_rating", None),
        "away_squad_recent_form_rating": getattr(away_squad, "recent_form_rating", None),
        "home_squad_recent_form_samples": getattr(home_squad, "recent_form_samples", None),
        "away_squad_recent_form_samples": getattr(away_squad, "recent_form_samples", None),
        "home_squad_attack": getattr(home_squad, "attack_rating", None),
        "away_squad_attack": getattr(away_squad, "attack_rating", None),
        "home_squad_defence": getattr(home_squad, "defence_rating", None),
        "away_squad_defence": getattr(away_squad, "defence_rating", None),
        "home_squad_availability_penalty": getattr(home_squad, "availability_penalty", None),
        "away_squad_availability_penalty": getattr(away_squad, "availability_penalty", None),
    }


def _selected_market_source(detail: SinaDetail, foreign: Any) -> dict[str, Any]:
    if foreign:
        raw = dict(getattr(foreign, "raw", {}) or {})
        return {**raw, "provider": "foreign_bookmakers"}
    raw = detail.raw if isinstance(detail.raw, dict) else {}
    return {
        key: raw[key]
        for key in (
            "market_consensus",
            "market_opening_consensus",
            "market_movement",
            "market_bookmakers",
            "market_dispersion",
            "asian_current_line",
            "asian_opening_line",
            "asian_line_movement",
            "asian_home_price_edge",
        )
        if key in raw
    } | {"provider": "sina_average_euro"}


def _data_usage_summary(audit: dict[str, Any], foreign_selected: bool) -> dict[str, list[str]]:
    numerical = ["1X2赔率", "近期状态"]
    if (audit.get("injuries") or {}).get("status") in {"available", "confirmed_empty"}:
        numerical.append("结构化伤停")
    if (audit.get("intelligence") or {}).get("status") == "available":
        numerical.append("结构化情报")
    if (audit.get("history") or {}).get("status") == "available":
        numerical.append("交锋平局率")
    if (audit.get("strength") or {}).get("status") in {"complete", "partial"}:
        numerical.append("球队实力")
    if (audit.get("xg") or {}).get("status") in {"complete", "partial"}:
        numerical.append("xG")
    if (audit.get("asian_handicap") or {}).get("status") == "available":
        numerical.append("亚洲让球")
    if (audit.get("totals") or {}).get("status") == "available":
        numerical.append("大小球")
    display_only = ["新闻标题", "主流媒体标题", "Polymarket"]
    if foreign_selected:
        numerical.append("国外公司赔率")
    return {"numerical": numerical, "display_only": display_only}


def _collection_audit(
    *,
    mode: str,
    odds_source: str,
    news: list[NewsItem],
    media_items: list[NewsItem],
    injury_news: list[NewsItem],
    detail: SinaDetail,
    strength_source: dict[str, Any],
    polymarket: Any,
    market_source: dict[str, Any],
) -> dict[str, Any]:
    detail_raw = detail.raw if isinstance(detail.raw, dict) else {}
    home_xg = int(strength_source.get("home_xg_matches") or 0)
    away_xg = int(strength_source.get("away_xg_matches") or 0)
    xg_status = "complete" if home_xg and away_xg else "partial" if home_xg or away_xg else "missing"
    injury_rows = int(detail_raw.get("injury_team1") or 0) + int(detail_raw.get("injury_team2") or 0)
    def provider_status(key: str, count: int) -> str:
        status = str(detail_raw.get(f"{key}_fetch_status") or "")
        if count:
            return "available"
        if status == "confirmed_empty":
            return "confirmed_empty"
        if status in {"request_failed", "provider_error", "missing_match_id"}:
            return status
        return "empty"

    return {
        "mode": mode,
        "odds": {"status": "missing" if odds_source == "default_placeholder" else "available", "provider": odds_source},
        "news": {"status": "available" if news else "empty_after_fallbacks", "count": len(news)},
        "mainstream_media": {"status": "available" if media_items else "empty", "count": len(media_items)},
        "injuries": {
            "status": "available" if injury_rows or injury_news else provider_status("injury", 0),
            "count": injury_rows + len(injury_news),
        },
        "history": {
            "status": provider_status("history", int(detail_raw.get("history_rows") or 0)),
            "count": int(detail_raw.get("history_rows") or 0),
        },
        "intelligence": {
            "status": provider_status("intelligence", int(detail_raw.get("intelligence_rows") or 0)),
            "count": int(detail_raw.get("intelligence_rows") or 0),
        },
        "odds_movement": {
            "status": "available" if detail_raw.get("market_movement") else provider_status("odds", int(detail_raw.get("odds_rows") or 0)),
            "bookmakers": int(detail_raw.get("market_bookmakers") or 0),
        },
        "asian_handicap": {
            "status": "available" if detail_raw.get("asian_rows") or market_source.get("spread_bookmakers") else provider_status("asian", 0),
            "count": int(detail_raw.get("asian_rows") or market_source.get("spread_bookmakers") or 0),
        },
        "totals": {
            "status": "available" if market_source.get("totals_bookmakers") else "not_available_from_provider",
            "count": int(market_source.get("totals_bookmakers") or 0),
        },
        "strength": {
            "status": strength_source.get("status") or ("not_requested" if mode == "simple" else "unmatched"),
            "provider": strength_source.get("provider") or "",
            "sofascore_status": ((strength_source.get("sofascore") or {}).get("status") if isinstance(strength_source.get("sofascore"), dict) else ""),
        },
        "xg": {"status": xg_status, "home_samples": home_xg, "away_samples": away_xg},
        "polymarket": {"status": "available" if polymarket else "unmatched"},
    }


def _apply_strength_to_signals(signals: dict[str, float], strength: Any) -> dict[str, float]:
    if not strength or not getattr(strength, "home", None) or not getattr(strength, "away", None):
        return signals
    updated = dict(signals)
    home = strength.home
    away = strength.away
    updated["home_form"] = _clamp_signal(home.rating)
    updated["away_form"] = _clamp_signal(away.rating)
    home_xg_edge = _xg_edge(home)
    away_xg_edge = _xg_edge(away)
    if home_xg_edge is not None:
        updated["home_motivation"] = _clamp_signal(updated["home_motivation"] + home_xg_edge * 0.08)
    if away_xg_edge is not None:
        updated["away_motivation"] = _clamp_signal(updated["away_motivation"] + away_xg_edge * 0.08)
    return updated


def _xg_edge(profile: Any) -> float | None:
    if profile.xg_for_per_match is None or profile.xg_against_per_match is None:
        return None
    return profile.xg_for_per_match - profile.xg_against_per_match


def _clamp_signal(value: float) -> float:
    return min(1.0, max(0.0, round(value, 3)))


def _data(raw: Any) -> Any:
    return raw if raw is not None else []


def _safe_len(raw: Any) -> int:
    try:
        return len(raw)
    except TypeError:
        return 0


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _keyword_score(text: str, keywords: list[str]) -> float:
    hits = sum(1 for keyword in keywords if keyword in text)
    return min(0.7, hits * 0.18)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _require_14(matches: list[RawMatch]) -> None:
    if len(matches) != 14:
        raise ValueError(f"Expected 14 matches, got {len(matches)}.")
