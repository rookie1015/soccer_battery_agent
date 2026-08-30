from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .review import ReviewReport


DIAGNOSTICS_FILENAME = "review_diagnostics.json"
MAX_DIAGNOSTIC_ISSUES = 52


def record_review_diagnostics(report: ReviewReport, report_dir: str | Path) -> dict[str, object]:
    path = Path(report_dir) / DIAGNOSTICS_FILENAME
    entries = _load_entries(path)
    issue = report.plan.issue.issue
    play_type = report.play_type
    entry = {
        "issue": issue,
        "play_type": play_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "outcome_hits": report.outcome_hits,
        "total": report.total,
        "tags": report.diagnostic_counts,
    }
    entries = [
        item
        for item in entries
        if not (
            item.get("issue") == issue
            and str(item.get("play_type") or "sfc14") == play_type
        )
    ]
    entries.insert(0, entry)
    entries = entries[:MAX_DIAGNOSTIC_ISSUES]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    aggregate: dict[str, int] = {}
    same_play_entries = [
        saved
        for saved in entries
        if str(saved.get("play_type") or "sfc14") == play_type
    ]
    for saved in same_play_entries:
        tags = saved.get("tags")
        if not isinstance(tags, dict):
            continue
        for label, count in tags.items():
            if isinstance(label, str) and isinstance(count, int):
                aggregate[label] = aggregate.get(label, 0) + count
    return {
        "issue_miss_count": report.total - report.outcome_hits,
        "issue_tags": _sorted_counts(report.diagnostic_counts),
        "history_issue_count": len(same_play_entries),
        "history_tags": _sorted_counts(aggregate),
    }


def _load_entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _sorted_counts(counts: dict[str, int]) -> list[dict[str, object]]:
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
