from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


ROI_SCHEMA = "ticket-roi-v1"
ROI_BACKTEST_SCHEMA = "roi-backtest-v1"


@dataclass(frozen=True)
class RoiRecord:
    issue: str
    status: str
    sfc14_cost_yuan: int
    choose9_cost_yuan: int
    total_cost_yuan: int
    gross_prize_yuan: int | None
    net_profit_yuan: int | None
    roi_percent: float | None
    won: bool | None
    provenance: str
    cost_source: str
    included_games: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"schema": ROI_SCHEMA, **self.__dict__}


def calculate_report_roi(report: dict[str, object], *, provenance: str = "saved_review") -> dict[str, object]:
    budget = report.get("budget") if isinstance(report.get("budget"), dict) else {}
    choose9 = report.get("choose9") if isinstance(report.get("choose9"), dict) else {}
    prize = report.get("prize") if isinstance(report.get("prize"), dict) else {}
    explicit_sfc_cost = _optional_int(budget.get("total_cost_yuan"))
    inferred_sfc_cost = _infer_sfc14_cost(report)
    sfc_cost = max(0, explicit_sfc_cost if explicit_sfc_cost is not None else inferred_sfc_cost or 0)
    choose9_cost_value = _optional_int(choose9.get("cost_yuan"))
    choose9_cost = max(0, choose9_cost_value or 0)
    total_cost = sfc_cost + choose9_cost
    gross = _applicable_gross_prize(prize, include_choose9=choose9_cost_value is not None)
    published = prize.get("status") == "published" and gross is not None
    cost_known = total_cost > 0
    net = gross - total_cost if published and cost_known else None
    roi = round(net / total_cost * 100, 2) if net is not None and total_cost > 0 else None
    record = RoiRecord(
        issue=str(report.get("issue") or ""),
        status="complete" if published and cost_known else "pending_prize" if not published else "incomplete_cost",
        sfc14_cost_yuan=sfc_cost,
        choose9_cost_yuan=choose9_cost,
        total_cost_yuan=total_cost,
        gross_prize_yuan=gross if published else None,
        net_profit_yuan=net,
        roi_percent=roi,
        won=(gross > 0) if published else None,
        provenance=provenance,
        cost_source=(
            "saved_budget"
            if explicit_sfc_cost is not None
            else "inferred_rectangular_ticket"
            if inferred_sfc_cost is not None
            else "unknown"
        ),
        included_games=("sfc14", "choose9") if choose9_cost_value is not None else ("sfc14",),
    )
    return record.as_dict()


def summarize_latest_issue_roi(entries: Iterable[dict[str, object]]) -> dict[str, object]:
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        if str(entry.get("kind") or "") != "review":
            continue
        report = entry.get("report")
        if not isinstance(report, dict):
            continue
        issue = str(report.get("issue") or entry.get("issue") or "").strip()
        if not issue or issue in seen or not issue.isdigit():
            continue
        seen.add(issue)
        provenance = _provenance(report, entry)
        records.append(calculate_report_roi(report, provenance=provenance))

    completed = [record for record in records if record["status"] == "complete"]
    chronological = sorted(completed, key=lambda record: str(record["issue"]))
    total_cost = sum(int(record["total_cost_yuan"]) for record in chronological)
    gross = sum(int(record["gross_prize_yuan"] or 0) for record in chronological)
    net = gross - total_cost
    cumulative = peak = 0
    max_drawdown = 0
    losing_streak = max_losing_streak = 0
    for record in chronological:
        profit = int(record["net_profit_yuan"] or 0)
        cumulative += profit
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        if profit < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0
    return {
        "schema": ROI_BACKTEST_SCHEMA,
        "scope": "latest_saved_review_per_issue",
        "record_count": len(records),
        "complete_count": len(completed),
        "pending_count": len(records) - len(completed),
        "incomplete_cost_count": sum(record["status"] == "incomplete_cost" for record in records),
        "saved_cost_count": sum(record["cost_source"] == "saved_budget" for record in completed),
        "inferred_cost_count": sum(
            record["cost_source"] == "inferred_rectangular_ticket" for record in completed
        ),
        "total_cost_yuan": total_cost,
        "gross_prize_yuan": gross,
        "net_profit_yuan": net,
        "roi_percent": round(net / total_cost * 100, 2) if total_cost else None,
        "winning_issue_count": sum(bool(record["won"]) for record in completed),
        "max_drawdown_yuan": max_drawdown,
        "max_consecutive_losing_issues": max_losing_streak,
        "records": sorted(records, key=lambda record: str(record["issue"])),
        "note": "每期只取历史索引中的最新复盘；旧记录成本按表格票面组合数推算，所有结果仅代表理论推荐方案的历史情景回放。",
    }


def write_roi_backtest(
    summary: dict[str, object],
    markdown_path: str | Path,
    json_path: str | Path | None = None,
) -> tuple[Path, Path]:
    markdown_target = Path(markdown_path)
    json_target = Path(json_path) if json_path is not None else markdown_target.with_suffix(".json")
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_target.write_text(render_roi_backtest(summary), encoding="utf-8")
    return markdown_target, json_target


def render_roi_backtest(summary: dict[str, object]) -> str:
    amount = lambda value: "待补全" if value is None else f"{int(value):,} 元"
    percent = lambda value: "待补全" if value is None else f"{float(value):.2f}%"
    lines = [
        "# 历史票面ROI回测",
        "",
        "> 每期只取历史索引中最新的一条复盘票面；这里只评估理论推荐方案的历史表现。",
        "",
        f"- 完整记录：{summary.get('complete_count', 0)}/{summary.get('record_count', 0)} 期",
        f"- 结构化保存成本：{summary.get('saved_cost_count', 0)} 期",
        f"- 从旧票面推算成本：{summary.get('inferred_cost_count', 0)} 期",
        f"- 成本不可确认：{summary.get('incomplete_cost_count', 0)} 期",
        f"- 总投入：{amount(summary.get('total_cost_yuan'))}",
        f"- 总奖金：{amount(summary.get('gross_prize_yuan'))}",
        f"- 净收益：{amount(summary.get('net_profit_yuan'))}",
        f"- ROI：{percent(summary.get('roi_percent'))}",
        f"- 有奖金期数：{summary.get('winning_issue_count', 0)}",
        f"- 最大回撤：{amount(summary.get('max_drawdown_yuan'))}",
        f"- 最长连续亏损：{summary.get('max_consecutive_losing_issues', 0)} 期",
        "",
        "| 期号 | 状态 | 玩法口径 | 来源 | 投入 | 奖金 | 净收益 | ROI |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for record in summary.get("records") or []:
        if not isinstance(record, dict):
            continue
        lines.append(
            f"| {record.get('issue', '')} | {record.get('status', '')} | "
            f"{'+'.join(record.get('included_games') or [])} | {record.get('provenance', '')} | "
            f"{amount(record.get('total_cost_yuan'))} | {amount(record.get('gross_prize_yuan'))} | "
            f"{amount(record.get('net_profit_yuan'))} | {percent(record.get('roi_percent'))} |"
        )
    lines.extend(["", str(summary.get("note") or ""), ""])
    return "\n".join(lines)


def _provenance(report: dict[str, object], entry: dict[str, object]) -> str:
    explicit = report.get("ticket_provenance")
    if isinstance(explicit, dict) and str(explicit.get("mode") or ""):
        return str(explicit["mode"])
    if not isinstance(report.get("budget"), dict):
        return "legacy_markdown_review"
    markdown = str(entry.get("markdown_text") or "")
    return "structured_review_snapshot" if "mobile-review-v1" in markdown else "legacy_markdown_review"


def _nonnegative_int(value: object) -> int:
    parsed = _optional_int(value)
    return max(0, parsed or 0)


def _infer_sfc14_cost(report: dict[str, object]) -> int | None:
    if report.get("legacy_line_portfolio_cost_unknown"):
        return None
    portfolio = report.get("line_portfolio")
    if isinstance(portfolio, dict):
        cost = _optional_int(portfolio.get("cost_yuan"))
        if cost is not None and cost > 0:
            return cost
    predictions = report.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != 14:
        return None
    units = 1
    for prediction in predictions:
        if not isinstance(prediction, dict):
            return None
        picks = prediction.get("picks")
        if isinstance(picks, list):
            count = len([pick for pick in picks if str(pick) in {"3", "1", "0"}])
        else:
            count = len([pick for pick in str(prediction.get("pick_text") or "").split("/") if pick in {"3", "1", "0"}])
        if count <= 0:
            return None
        units *= count
    return units * 2


def _applicable_gross_prize(prize: dict[str, object], *, include_choose9: bool) -> int | None:
    sfc = prize.get("sfc14") if isinstance(prize.get("sfc14"), dict) else None
    choose9 = prize.get("choose9") if isinstance(prize.get("choose9"), dict) else None
    if sfc is not None:
        sfc_total = _optional_int(sfc.get("total_prize_yuan"))
        if sfc_total is None:
            return None
        choose9_total = _optional_int(choose9.get("total_prize_yuan")) if include_choose9 and choose9 else 0
        return None if choose9_total is None else sfc_total + choose9_total
    return _optional_int(prize.get("total_prize_yuan"))


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
