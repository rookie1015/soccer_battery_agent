from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DRAW_ECONOMICS_SCHEMA = "official-draw-economics-v1"
SPORTTERY_RULE_REFERENCE = "https://www.sporttery.cn/help/2868.html?gid=6"
SPORTTERY_CHOOSE9_RULE_REFERENCE = "https://www.sporttery.cn/help/2865.html?gid=6"
RULE_VERIFIED_ON = "2026-09-15"


@dataclass(frozen=True)
class OfficialPrize:
    draw_date: str = ""
    sfc14_first_yuan: int | None = None
    sfc14_second_yuan: int | None = None
    choose9_yuan: int | None = None
    source: str = "中国体彩网官方开奖"

    @property
    def published(self) -> bool:
        return any(
            value is not None
            for value in (self.sfc14_first_yuan, self.sfc14_second_yuan, self.choose9_yuan)
        )


@dataclass(frozen=True)
class PrizeLevelEconomics:
    name: str
    winning_lines: int | None = None
    prize_per_line_yuan: int | None = None
    total_prize_yuan: int | None = None


@dataclass(frozen=True)
class OfficialDrawEconomics:
    issue: str
    draw_date: str
    sfc14_sales_yuan: int | None
    choose9_sales_yuan: int | None
    sfc14_first: PrizeLevelEconomics
    sfc14_second: PrizeLevelEconomics
    choose9: PrizeLevelEconomics
    pool_balance_before_yuan: int | None = None
    pool_balance_after_yuan: int | None = None
    choose9_pool_balance_after_yuan: int | None = None
    sfc14_flow_fund_yuan: int | None = None
    choose9_flow_fund_yuan: int | None = None
    sfc14_surplus_yuan: int | None = None
    choose9_surplus_yuan: int | None = None
    source: str = "中国体彩网官方开奖"
    source_url: str = ""
    fetched_at: str = ""
    raw_response_sha256: str = ""
    rule_reference: str = SPORTTERY_RULE_REFERENCE
    choose9_rule_reference: str = SPORTTERY_CHOOSE9_RULE_REFERENCE
    rule_verified_on: str = RULE_VERIFIED_ON

    @property
    def prize(self) -> OfficialPrize:
        return OfficialPrize(
            draw_date=self.draw_date,
            sfc14_first_yuan=self.sfc14_first.prize_per_line_yuan,
            sfc14_second_yuan=self.sfc14_second.prize_per_line_yuan,
            choose9_yuan=self.choose9.prize_per_line_yuan,
            source=self.source,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"schema": DRAW_ECONOMICS_SCHEMA, **asdict(self)}


def parse_official_draw_economics(
    issue: str,
    row: dict[str, Any],
    *,
    source_url: str = "",
    raw_response: object | None = None,
    fetched_at: datetime | None = None,
) -> OfficialDrawEconomics:
    first = _find_level(row.get("prizeLevelList"), "一等奖", fallback_group="10")
    second = _find_level(row.get("prizeLevelList"), "二等奖", fallback_group="20")
    choose9 = _find_level(row.get("prizeLevelListRj"), "任选9场", fallback_group="1010")
    fetched = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_sha = ""
    if raw_response is not None:
        canonical = json.dumps(raw_response, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return OfficialDrawEconomics(
        issue=issue,
        draw_date=str(row.get("lotteryDrawTime") or "").strip()[:10],
        sfc14_sales_yuan=_integer(row.get("totalSaleAmount")),
        choose9_sales_yuan=_integer(row.get("totalSaleAmountRj")),
        sfc14_first=_parse_level(first, "一等奖"),
        sfc14_second=_parse_level(second, "二等奖"),
        choose9=_parse_level(choose9, "任选9场"),
        pool_balance_before_yuan=_integer(row.get("poolBalance")),
        pool_balance_after_yuan=_integer(row.get("poolBalanceAfterdraw")),
        choose9_pool_balance_after_yuan=_integer(row.get("poolBalanceAfterdrawRj")),
        sfc14_flow_fund_yuan=_integer(row.get("drawFlowFund")),
        choose9_flow_fund_yuan=_integer(row.get("drawFlowFundRj")),
        sfc14_surplus_yuan=_integer(row.get("surplusAmount")),
        choose9_surplus_yuan=_integer(row.get("surplusAmountRj")),
        source_url=source_url,
        fetched_at=fetched.isoformat(),
        raw_response_sha256=raw_sha,
    )


def write_draw_economics_snapshot(
    path: str | Path,
    economics: OfficialDrawEconomics,
    raw_response: object,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": DRAW_ECONOMICS_SCHEMA,
        "economics": economics.as_dict(),
        "raw_response": raw_response,
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def _find_level(value: object, label: str, *, fallback_group: str) -> dict[str, Any]:
    rows = value if isinstance(value, list) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get("prizeLevel") or "").strip() == label:
            return row
    for row in rows:
        if isinstance(row, dict) and str(row.get("group") or "").strip() == fallback_group:
            return row
    return {}


def _parse_level(value: dict[str, Any], label: str) -> PrizeLevelEconomics:
    return PrizeLevelEconomics(
        name=label,
        winning_lines=_integer(value.get("stakeCount")),
        prize_per_line_yuan=_integer(value.get("stakeAmountFormat") or value.get("stakeAmount")),
        total_prize_yuan=_integer(value.get("totalPrizeamount")),
    )


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list, tuple)):
        return None
    digits = re.sub(r"[^0-9-]", "", str(value).strip())
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None
