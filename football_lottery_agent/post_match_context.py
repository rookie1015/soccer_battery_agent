from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .collectors import NewsItem, search_web_news
from .review import ReviewReport


_EVIDENCE_RULES = (
    (
        "关键伤停或临场阵容变化",
        "injury absence suspended lineup missing 伤停 缺阵 停赛 首发 阵容",
        ("injur", "absen", "suspend", "lineup", "missing", "伤", "缺阵", "停赛", "首发", "阵容"),
    ),
    (
        "恶劣天气或场地条件",
        "weather rain wind snow storm pitch 天气 大雨 大风 暴雨 积水 场地",
        ("weather", "rain", "wind", "snow", "storm", "pitch", "天气", "大雨", "大风", "暴雨", "积水", "场地"),
    ),
    (
        "红牌、VAR 或争议判罚",
        "red card VAR referee penalty controversy 红牌 VAR 裁判 点球 判罚 争议",
        ("red card", "var", "referee", "penalty", "controvers", "红牌", "裁判", "点球", "判罚", "争议"),
    ),
)


def find_post_match_evidence(
    report: ReviewReport,
    cache_dir: str | Path,
    max_matches: int = 5,
) -> dict[int, list[dict[str, object]]]:
    """Find post-match reporting for misses without treating search results as proof."""
    misses = [row for row in report.rows if not row.outcome_hit][:max_matches]
    jobs = [
        (row.prediction.match.seq, label, _query(row, terms), keywords)
        for row in misses
        for label, terms, keywords in _EVIDENCE_RULES
    ]
    found: dict[int, list[dict[str, object]]] = {row.prediction.match.seq: [] for row in misses}
    if not jobs:
        return found

    root = Path(cache_dir)
    with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as executor:
        futures = [
            executor.submit(search_web_news, query, root / "web", 4)
            for _, _, query, _ in jobs
        ]
        for (seq, label, _, keywords), future in zip(jobs, futures):
            try:
                items = future.result()
            except Exception:
                continue
            relevant = [item for item in items if _matches_keywords(item, keywords)][:2]
            if relevant:
                found[seq].append(_evidence(label, relevant))
    return found


def _query(row, terms: str) -> str:
    match = row.prediction.match
    date = match.kickoff.strftime("%Y-%m-%d")
    return f'"{match.home}" "{match.away}" {date} football {terms}'


def _matches_keywords(item: NewsItem, keywords: tuple[str, ...]) -> bool:
    title = item.title.casefold()
    return any(keyword.casefold() in title for keyword in keywords)


def _evidence(label: str, items: list[NewsItem]) -> dict[str, object]:
    return {
        "label": label,
        "summary": "；".join(item.title for item in items),
        "sources": [
            {"title": item.title, "url": item.link, "published": item.published}
            for item in items
        ],
    }


def evidence_summary(evidence: list[dict[str, object]]) -> str:
    labels = [str(item.get("label") or "") for item in evidence if item.get("label")]
    return "、".join(labels) or "未找到可验证的赛后报道"


def normalize_evidence(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
