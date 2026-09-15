from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


PURCHASE_RECORD_SCHEMA = "purchase-record-v1"
PURCHASE_STATUSES = {"purchased", "partial", "not_purchased"}
PLAY_TYPES = {"sfc14", "choose9"}


def normalize_purchase_record(payload: dict[str, Any]) -> dict[str, object]:
    issue = str(payload.get("issue") or "").strip()
    if not issue or not re.fullmatch(r"[A-Za-z0-9_-]+", issue):
        raise ValueError("购买记录缺少有效期号。")
    status = str(payload.get("status") or "").strip()
    if status not in PURCHASE_STATUSES:
        raise ValueError("购买状态必须是 purchased、partial 或 not_purchased。")
    tickets = payload.get("tickets")
    ticket_rows = tickets if isinstance(tickets, list) else []
    normalized_tickets = [_normalize_ticket(row) for row in ticket_rows if isinstance(row, dict)]
    if status in {"purchased", "partial"} and not normalized_tickets:
        raise ValueError("已购买或部分购买记录必须包含实际票面。")
    ticket_cost = sum(int(row["cost_yuan"]) for row in normalized_tickets)
    explicit_amount = _optional_nonnegative_int(payload.get("actual_amount_yuan"))
    amount = ticket_cost if explicit_amount is None else explicit_amount
    if status == "not_purchased":
        if normalized_tickets or amount:
            raise ValueError("未购买记录不能包含票面或购买金额。")
        amount = 0
    elif amount <= 0:
        raise ValueError("实际购买金额必须大于 0。")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema": PURCHASE_RECORD_SCHEMA,
        "issue": issue,
        "status": status,
        "actual_purchase_confirmed": status in {"purchased", "partial"},
        "actual_amount_yuan": amount,
        "ticket_cost_yuan": ticket_cost,
        "amount_matches_ticket_cost": amount == ticket_cost,
        "purchased_at": (
            str(payload.get("purchased_at") or "").strip() or now
            if status in {"purchased", "partial"}
            else ""
        ),
        "recommendation_analysis_id": str(payload.get("recommendation_analysis_id") or "").strip(),
        "strategy_version": str(payload.get("strategy_version") or "").strip(),
        "tickets": normalized_tickets,
        "actual_gross_prize_yuan": _optional_nonnegative_int(payload.get("actual_gross_prize_yuan")),
        "notes": str(payload.get("notes") or "").strip(),
        "recorded_at": now,
        "updated_at": now,
    }


def save_purchase_record(work_dir: str | Path, payload: dict[str, Any]) -> dict[str, object]:
    record = normalize_purchase_record(payload)
    target = purchase_record_path(work_dir, str(record["issue"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return record


def load_purchase_record(work_dir: str | Path, issue: str) -> dict[str, object] | None:
    target = purchase_record_path(work_dir, issue)
    if not target.exists():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("schema") == PURCHASE_RECORD_SCHEMA else None


def purchase_record_path(work_dir: str | Path, issue: str) -> Path:
    clean_issue = str(issue).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", clean_issue):
        raise ValueError("购买记录期号无效。")
    return Path(work_dir) / "data" / "purchases" / f"{clean_issue}.json"


def _normalize_ticket(value: dict[str, Any]) -> dict[str, object]:
    play_type = str(value.get("play_type") or "").strip()
    if play_type not in PLAY_TYPES:
        raise ValueError("实际票面玩法必须是 sfc14 或 choose9。")
    lines = value.get("lines")
    if isinstance(lines, list) and len(lines) > 10_000:
        raise ValueError("单个实际票面最多保存 10000 注。")
    normalized_lines = [_normalize_line(line, play_type) for line in lines] if isinstance(lines, list) else []
    if not normalized_lines:
        raise ValueError("每个实际票面至少需要一注。")
    computed_cost = len(normalized_lines) * 2
    cost = _optional_nonnegative_int(value.get("cost_yuan"))
    if cost is None:
        cost = computed_cost
    return {
        "play_type": play_type,
        "cost_yuan": cost,
        "computed_cost_yuan": computed_cost,
        "cost_matches_lines": cost == computed_cost,
        "lines": normalized_lines,
    }


def _normalize_line(value: object, play_type: str) -> dict[str, object]:
    if isinstance(value, str):
        outcomes = [item for item in re.split(r"[-,/\s]+", value.strip()) if item]
        sequences = list(range(1, len(outcomes) + 1))
    elif isinstance(value, dict):
        outcomes = [str(item) for item in value.get("outcomes", [])]
        raw_sequences = value.get("sequences")
        sequences = [int(item) for item in raw_sequences] if isinstance(raw_sequences, list) else list(range(1, len(outcomes) + 1))
    else:
        raise ValueError("实际票面注格式无效。")
    expected = 14 if play_type == "sfc14" else 9
    if len(outcomes) != expected or len(sequences) != expected:
        raise ValueError(f"{play_type} 每注必须包含 {expected} 场。")
    if any(outcome not in {"3", "1", "0"} for outcome in outcomes):
        raise ValueError("实际票面只允许 3、1、0。")
    if len(set(sequences)) != len(sequences) or any(seq < 1 or seq > 14 for seq in sequences):
        raise ValueError("实际票面场次序号无效。")
    return {"sequences": sequences, "outcomes": outcomes}


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("金额必须是非负整数。") from exc
    if result < 0:
        raise ValueError("金额必须是非负整数。")
    return result
