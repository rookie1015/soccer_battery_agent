from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .collectors import collect_issue
from .history import archive_report, load_history_entries
from .html_report import write_analysis_html
from .loader import load_issue
from .mobile_api import serialize_ticket_plan
from .models import Match, Odds, Signals
from .predictor import OUTCOME_LABELS, predict_match
from .report import write_report
from .strategy import build_ticket_plan


def run_health() -> dict[str, object]:
    return {"ok": True, "service": "football-lottery-agent-local"}


def run_analysis(
    payload: dict[str, Any],
    work_dir: str | Path,
) -> dict[str, object]:
    issue = str(payload.get("issue") or "").strip()
    if not issue:
        raise ValueError("请填写期号。")
    strength_xg_matches = int(payload.get("strength_xg_matches") or 8)
    if strength_xg_matches < 0 or strength_xg_matches > 20:
        raise ValueError("xG 样本场次必须是 0 到 20 之间的整数。")

    root = Path(work_dir)
    data_dir = root / "data"
    report_dir = root / "reports"
    history_dir = report_dir / "history"
    cache_dir = root / "cache"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    issue_path = data_dir / "collected_issue.json"
    markdown_path = report_dir / f"{_slug(issue)}_report.md"
    html_path = report_dir / f"{_slug(issue)}_report.html"

    collect_issue(
        output_path=issue_path,
        issue=issue,
        cache_dir=cache_dir,
        strength_model=False,
        strength_xg_matches=strength_xg_matches,
        skip_context_fetches=True,
        sina_odds_only=True,
    )
    plan = build_ticket_plan(load_issue(issue_path))
    write_report(plan, markdown_path)
    write_analysis_html(plan, html_path)
    history_path = archive_report(
        "analysis",
        plan.issue.issue,
        html_path,
        markdown_path,
        history_dir=history_dir,
    )

    return {
        "ok": True,
        "message": f"{issue} 分析报告已在手机本机生成。",
        "report": serialize_ticket_plan(plan),
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "history_path": str(history_path),
    }


def run_history(work_dir: str | Path) -> dict[str, object]:
    history_dir = Path(work_dir) / "reports" / "history"
    entries = []
    for item in load_history_entries(history_dir):
        entry = dict(item)
        markdown = str(entry.get("markdown") or "")
        html = str(entry.get("html") or "")
        entry["html_url"] = str((history_dir / html).resolve()) if html else ""
        entry["markdown_url"] = str((history_dir / markdown).resolve()) if markdown else ""
        entry["markdown_text"] = _read_history_text(history_dir, markdown)
        entries.append(entry)
    return {"ok": True, "entries": entries}


def _read_history_text(history_dir: Path, relative_path: str) -> str:
    if not relative_path:
        return ""
    path = (history_dir / relative_path).resolve()
    try:
        path.relative_to(history_dir.resolve())
    except ValueError:
        return ""
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def run_single_prediction(payload: dict[str, Any], work_dir: str | Path) -> dict[str, object]:
    home = str(payload.get("home") or "").strip()
    away = str(payload.get("away") or "").strip()
    if not home or not away:
        raise ValueError("请填写主队和客队。")
    if home.casefold() == away.casefold():
        raise ValueError("主队和客队不能相同。")

    match = _find_collected_match(home, away, Path(work_dir) / "data" / "collected_issue.json")
    if match:
        data_source = "手机本机最近一次采集的赔率、球队状态和伤停信号"
    else:
        odds_values = [str(payload.get(key) or "").strip() for key in ("home_odds", "draw_odds", "away_odds")]
        if any(odds_values) and not all(odds_values):
            raise ValueError("欧赔请填写完整的主胜、平局和客胜三项，或全部留空。")
        if all(odds_values):
            values = [float(value) for value in odds_values]
            if any(value <= 1.0 for value in values):
                raise ValueError("欧赔必须大于 1.00。")
            odds = Odds(home=values[0], draw=values[1], away=values[2])
            data_source = "手工填写的欧洲赔率；球队状态按中性值处理"
        else:
            odds = Odds(home=2.60, draw=3.20, away=2.70)
            data_source = "未匹配最近采集赛事且未填写赔率，使用均衡基准"
        match = Match(
            seq=1,
            kickoff=datetime.now().astimezone(),
            league="单场预测",
            home=home,
            away=away,
            odds=odds,
            signals=Signals(),
        )

    prediction = predict_match(match)
    return {
        "ok": True,
        "message": "单场比分预测已在手机本机生成。",
        "home": prediction.match.home,
        "away": prediction.match.away,
        "scorelines": [
            {"score": item.text, "probability": round(item.probability * 100, 1)}
            for item in prediction.scorelines
        ],
        "probabilities": {
            "home": round(prediction.probabilities["3"] * 100, 1),
            "draw": round(prediction.probabilities["1"] * 100, 1),
            "away": round(prediction.probabilities["0"] * 100, 1),
        },
        "pick_label": " / ".join(OUTCOME_LABELS[item] for item in prediction.picks),
        "confidence": prediction.confidence,
        "risk": prediction.risk,
        "reasons": list(prediction.reasons),
        "data_source": data_source,
    }


def _find_collected_match(home: str, away: str, issue_path: Path) -> Match | None:
    if not issue_path.exists():
        return None
    issue = load_issue(issue_path)
    home_key = _team_key(home)
    away_key = _team_key(away)
    return next(
        (
            match
            for match in issue.matches
            if _team_key(match.home) == home_key and _team_key(match.away) == away_key
        ),
        None,
    )


def _team_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _slug(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    clean = clean.strip("-")
    return clean or "report"
