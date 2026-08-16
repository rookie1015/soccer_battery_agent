from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .http_utils import read_url_text
from .team_identity import team_match_score


FIVE_HUNDRED_SFC_URL = "https://trade.500.com/sfc/?expect="
ZGZCW_SFC_URL = "https://cp.zgzcw.com/lottery/zcplayvs.action"
FOOTBALL_DATA_MATCHES_URL = "https://api.football-data.org/v4/matches"
SOURCE_CACHE_SECONDS = 300


@dataclass(frozen=True)
class AuxiliaryMatch:
    provider: str
    seq: int | None
    home: str
    away: str
    kickoff: str
    odds: tuple[float, float, float] | None = None
    asian_handicap: str = ""
    status: str = "scheduled"
    source_url: str = ""
    provider_match_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_match_id": self.provider_match_id,
            "seq": self.seq,
            "home": self.home,
            "away": self.away,
            "kickoff": self.kickoff,
            "odds": list(self.odds) if self.odds else None,
            "asian_handicap": self.asian_handicap,
            "status": self.status,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class AuxiliaryResult:
    by_seq: dict[int, tuple[AuxiliaryMatch, ...]]
    audit: dict[str, Any]


def fetch_free_auxiliary_sources(
    matches: list[Any],
    issue: str,
    cache_dir: str | Path,
    *,
    football_data_api_key: str | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> AuxiliaryResult:
    """Fetch free sources which verify or fill gaps in the Sina payload.

    500.com and ZGZCW are issue-specific cross-checks. football-data.org is
    optional because its free plan still requires a token. Failures here never
    fail the analysis: these providers are deliberately auxiliary.
    """
    cache = Path(cache_dir)
    provider_rows: dict[str, list[AuxiliaryMatch]] = {}
    audits: dict[str, dict[str, Any]] = {}

    calls: list[tuple[str, Callable[[], list[AuxiliaryMatch]]]] = [
        ("500.com", lambda: fetch_500_issue(issue, cache, cancel_check=cancel_check)),
        ("zgzcw", lambda: fetch_zgzcw_issue(issue, cache, cancel_check=cancel_check)),
    ]
    if football_data_api_key:
        calls.append(
            (
                "football-data.org",
                lambda: fetch_football_data_matches(
                    matches,
                    cache,
                    football_data_api_key,
                    cancel_check=cancel_check,
                ),
            )
        )
    else:
        audits["football-data.org"] = {
            "status": "not_configured",
            "configured": False,
            "matched_matches": 0,
            "message": "未配置免费 Token，本次未调用 football-data.org。",
        }

    for provider, call in calls:
        if cancel_check is not None:
            cancel_check()
        try:
            rows = call()
        except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            provider_rows[provider] = []
            audits[provider] = {
                "status": "request_failed",
                "configured": provider != "football-data.org" or bool(football_data_api_key),
                "matched_matches": 0,
                "message": _safe_failure_message(provider, exc),
            }
        else:
            provider_rows[provider] = rows
            audits[provider] = {
                "status": "available" if rows else "empty",
                "configured": True,
                "received_matches": len(rows),
                "matched_matches": 0,
                "message": "已获取辅助数据。" if rows else "辅助源未返回可用比赛。",
            }

    by_seq: dict[int, list[AuxiliaryMatch]] = {int(match.seq): [] for match in matches}
    for provider, rows in provider_rows.items():
        matched_count = 0
        for row in rows:
            seq = _match_row_to_local(row, matches)
            if seq is None:
                continue
            by_seq.setdefault(seq, []).append(row)
            matched_count += 1
        audits[provider]["matched_matches"] = matched_count
        if rows and not matched_count:
            audits[provider]["status"] = "unmatched"
            audits[provider]["message"] = "已收到数据，但没有安全匹配到本期球队。"

    return AuxiliaryResult(
        by_seq={seq: tuple(rows) for seq, rows in by_seq.items()},
        audit={
            "role": "sina_auxiliary_verification",
            "issue": issue,
            "providers": audits,
        },
    )


def fetch_500_issue(
    issue: str,
    cache_dir: Path,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> list[AuxiliaryMatch]:
    url = f"{FIVE_HUNDRED_SFC_URL}{urllib.parse.quote(issue)}"
    html = _fetch_cached_text(url, cache_dir, encoding="gb18030", cancel_check=cancel_check)
    selected_issue = re.search(r'class="(?:on|chked)"[^>]*>[\s\S]{0,200}?data-expect="(\d+)"', html)
    if selected_issue and selected_issue.group(1) != issue:
        raise ValueError(f"500.com returned issue {selected_issue.group(1)}")
    parser = _FiveHundredParser(issue, url)
    parser.feed(html)
    return parser.matches


def fetch_zgzcw_issue(
    issue: str,
    cache_dir: Path,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> list[AuxiliaryMatch]:
    url = f"{ZGZCW_SFC_URL}?{urllib.parse.urlencode({'lotteryId': '13', 'issue': issue})}"
    text = _fetch_cached_text(
        url,
        cache_dir,
        encoding="utf-8",
        headers={"Referer": "https://cp.zgzcw.com/zgzcw/lottery/"},
        cancel_check=cancel_check,
    )
    payload = json.loads(text)
    raw_matches = payload.get("matchInfo") if isinstance(payload, dict) else None
    if not isinstance(raw_matches, list):
        raise ValueError("ZGZCW response did not contain matchInfo")
    result: list[AuxiliaryMatch] = []
    for index, item in enumerate(raw_matches, start=1):
        if not isinstance(item, dict) or str(item.get("issue") or issue) != issue:
            continue
        result.append(
            AuxiliaryMatch(
                provider="zgzcw",
                seq=index,
                home=str(item.get("hostNameFull") or item.get("hostName") or "").strip(),
                away=str(item.get("guestNameFull") or item.get("guestName") or "").strip(),
                kickoff=str(item.get("gameStartDate") or "").strip(),
                odds=_parse_space_odds(item.get("europeSp")),
                asian_handicap=str(item.get("yapan") or "").strip(),
                status="stopped" if str(item.get("isStop") or "").casefold() == "true" else "scheduled",
                source_url=url,
                provider_match_id=str(item.get("playId") or "").strip(),
            )
        )
    return result


def fetch_football_data_matches(
    matches: list[Any],
    cache_dir: Path,
    api_key: str,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> list[AuxiliaryMatch]:
    dates = sorted({_kickoff_date(str(match.kickoff)) for match in matches if _kickoff_date(str(match.kickoff))})
    result: list[AuxiliaryMatch] = []
    for day in dates[:7]:
        if cancel_check is not None:
            cancel_check()
        url = f"{FOOTBALL_DATA_MATCHES_URL}?{urllib.parse.urlencode({'dateFrom': day, 'dateTo': day})}"
        text = _fetch_cached_text(
            url,
            cache_dir,
            encoding="utf-8",
            headers={"X-Auth-Token": api_key},
            cancel_check=cancel_check,
        )
        payload = json.loads(text)
        for item in payload.get("matches", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            home = item.get("homeTeam") if isinstance(item.get("homeTeam"), dict) else {}
            away = item.get("awayTeam") if isinstance(item.get("awayTeam"), dict) else {}
            status = str(item.get("status") or "scheduled").casefold()
            result.append(
                AuxiliaryMatch(
                    provider="football-data.org",
                    seq=None,
                    home=str(home.get("name") or home.get("shortName") or "").strip(),
                    away=str(away.get("name") or away.get("shortName") or "").strip(),
                    kickoff=str(item.get("utcDate") or "").strip(),
                    status=status,
                    source_url=url,
                    provider_match_id=str(item.get("id") or "").strip(),
                )
            )
    return result


def auxiliary_odds(rows: tuple[AuxiliaryMatch, ...]) -> tuple[float, float, float] | None:
    odds_rows = [row.odds for row in rows if row.odds]
    if not odds_rows:
        return None
    return tuple(round(sum(values) / len(values), 3) for values in zip(*odds_rows))  # type: ignore[return-value]


def auxiliary_notes(
    rows: tuple[AuxiliaryMatch, ...],
    sina_odds: Any,
    sina_kickoff: str = "",
) -> list[str]:
    if not rows:
        return []
    providers = "、".join(dict.fromkeys(_provider_label(row.provider) for row in rows))
    odds_providers = "、".join(
        dict.fromkeys(_provider_label(row.provider) for row in rows if row.odds)
    )
    notes: list[str] = []
    status_rows = [row for row in rows if row.status in {"postponed", "cancelled", "suspended", "stopped"}]
    if status_rows:
        status_text = "、".join(
            f"{_provider_label(row.provider)}={row.status}" for row in status_rows
        )
        notes.append(f"辅助信源状态提示：{status_text}；需以赛事组织方和体彩公告最终确认。")
    kickoff_differences = _kickoff_differences(rows, sina_kickoff)
    if kickoff_differences:
        notes.append(
            "辅助信源赛程差异："
            + "、".join(kickoff_differences)
            + f"，新浪为{sina_kickoff}；仅提示差异，未覆盖新浪主源。"
        )
    aux_odds = auxiliary_odds(rows)
    if not aux_odds:
        notes.append(f"辅助信源核验：{providers}已匹配本场赛程，未提供可比较欧赔。")
        return notes
    if sina_odds is None:
        notes.append(f"辅助信源补缺：新浪欧赔缺失，使用{odds_providers}公开欧赔均值。")
        return notes
    sina_probs = _implied_probabilities((float(sina_odds.home), float(sina_odds.draw), float(sina_odds.away)))
    aux_probs = _implied_probabilities(aux_odds)
    largest_gap = max(abs(a - b) for a, b in zip(sina_probs, aux_probs))
    sina_direction = max(range(3), key=sina_probs.__getitem__)
    aux_direction = max(range(3), key=aux_probs.__getitem__)
    if sina_direction != aux_direction or largest_gap >= 0.08:
        notes.append(
            f"辅助信源核验：{odds_providers}与新浪赔率存在明显差异（最大去水概率差{largest_gap:.1%}），"
            "仅提示差异，未覆盖新浪主源。"
        )
        return notes
    notes.append(f"辅助信源核验：{odds_providers}公开赔率与新浪市场方向一致。")
    return notes


def _kickoff_differences(rows: tuple[AuxiliaryMatch, ...], sina_kickoff: str) -> list[str]:
    reference = _parse_kickoff(sina_kickoff, None)
    if reference is None:
        return []
    differences: list[str] = []
    for row in rows:
        value = _parse_kickoff(row.kickoff, reference)
        if value is None:
            continue
        left = value.astimezone(timezone.utc) if value.tzinfo else value
        right = reference.astimezone(timezone.utc) if reference.tzinfo else reference
        if abs((left - right).total_seconds()) >= 2 * 3600:
            differences.append(f"{_provider_label(row.provider)}显示{row.kickoff}")
    return differences


def _parse_kickoff(value: str, reference: datetime | None) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        short = re.fullmatch(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
        if not short or reference is None:
            return None
        parsed = reference.replace(
            month=int(short.group(1)),
            day=int(short.group(2)),
            hour=int(short.group(3)),
            minute=int(short.group(4)),
            second=0,
            microsecond=0,
        )
    if parsed.tzinfo is None and reference is not None and reference.tzinfo is not None:
        parsed = parsed.replace(tzinfo=reference.tzinfo)
    return parsed


def _match_row_to_local(row: AuxiliaryMatch, matches: list[Any]) -> int | None:
    if row.seq is not None and 1 <= row.seq <= len(matches):
        local = matches[row.seq - 1]
        # Both Chinese sites expose the fixed, issue-specific SFC order. Their
        # club labels are often shortened beyond safe alias matching, so the
        # already validated issue + sequence is the stable identity here.
        if int(local.seq) == row.seq and row.provider in {"500.com", "zgzcw"}:
            return row.seq
    candidates = [(int(match.seq), _pair_score(match, row)) for match in matches]
    candidates = [candidate for candidate in candidates if candidate[1] >= 1.6]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[1], item[0]))
    if len(candidates) > 1 and candidates[0][1] == candidates[1][1]:
        return None
    return candidates[0][0]


def _pair_score(local: Any, row: AuxiliaryMatch) -> float:
    return team_match_score(str(local.home), row.home) + team_match_score(str(local.away), row.away)


def _parse_space_odds(value: Any) -> tuple[float, float, float] | None:
    parts = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    if len(parts) < 3:
        return None
    odds = tuple(float(item) for item in parts[:3])
    if any(item <= 1.0 for item in odds):
        return None
    return odds  # type: ignore[return-value]


def _parse_comma_odds(value: str) -> tuple[float, float, float] | None:
    return _parse_space_odds(value.replace(",", " "))


def _implied_probabilities(odds: tuple[float, float, float]) -> tuple[float, float, float]:
    inverse = tuple(1.0 / value for value in odds)
    total = sum(inverse)
    return tuple(value / total for value in inverse)  # type: ignore[return-value]


def _kickoff_date(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else ""


def _provider_label(provider: str) -> str:
    return {
        "500.com": "500网",
        "zgzcw": "中国足彩网",
        "football-data.org": "football-data.org",
    }.get(provider, provider)


def _safe_failure_message(provider: str, exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in {401, 403} and provider == "football-data.org":
            return "football-data.org 免费 Token 无效或无权访问。"
        return f"{_provider_label(provider)}返回 HTTP {exc.code}。"
    return f"{_provider_label(provider)}本次未能获取，已保留新浪主源。"


def _fetch_cached_text(
    url: str,
    cache_dir: Path,
    *,
    encoding: str,
    headers: dict[str, str] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"aux_{hashlib.sha256((url + '|' + encoding).encode('utf-8')).hexdigest()}.txt"
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime <= SOURCE_CACHE_SECONDS:
        return cache_path.read_text(encoding="utf-8", errors="replace")
    request_headers = {
        "Accept": "application/json,text/html,*/*",
        "User-Agent": "Mozilla/5.0 football-lottery-agent/0.3",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers)
    try:
        text = read_url_text(
            request,
            timeout=8,
            attempts=2,
            encoding=encoding,
            cancel_check=cancel_check,
        )
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")
        raise
    cache_path.write_text(text, encoding="utf-8")
    return text


class _FiveHundredParser(HTMLParser):
    def __init__(self, issue: str, source_url: str) -> None:
        super().__init__()
        self.issue = issue
        self.source_url = source_url
        self.matches: list[AuxiliaryMatch] = []
        self._row: dict[str, str] | None = None
        self._in_kickoff = False
        self._kickoff_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "tr" and "bet-tb-tr" in values.get("class", "").split():
            self._row = values
            self._kickoff_parts = []
        elif tag == "td" and self._row is not None and "td-endtime" in values.get("class", "").split():
            self._in_kickoff = True

    def handle_data(self, data: str) -> None:
        if self._in_kickoff:
            self._kickoff_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_kickoff:
            self._in_kickoff = False
        if tag != "tr" or self._row is None:
            return
        seq_text = self._row.get("data-cid", "")
        versus = self._row.get("data-vs", "")
        pair = re.split(r"\s*vs\s*", versus, maxsplit=1, flags=re.IGNORECASE)
        if seq_text.isdigit() and len(pair) == 2:
            seq = int(seq_text)
            kickoff = " ".join(self._kickoff_parts).strip()
            self.matches.append(
                AuxiliaryMatch(
                    provider="500.com",
                    seq=seq,
                    home=pair[0].strip(),
                    away=pair[1].strip(),
                    kickoff=kickoff,
                    odds=_parse_comma_odds(self._row.get("data-bjpl", "")),
                    asian_handicap=self._row.get("data-asian", ""),
                    status="finished" if self._row.get("data-isend") == "1" else "scheduled",
                    source_url=self.source_url,
                    provider_match_id=str(seq),
                )
            )
        self._row = None
        self._kickoff_parts = []
