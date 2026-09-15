import json
from pathlib import Path
from tempfile import TemporaryDirectory

from football_lottery_agent.draw_economics import (
    DRAW_ECONOMICS_SCHEMA,
    parse_official_draw_economics,
    write_draw_economics_snapshot,
)


def test_parse_and_persist_official_draw_economics_contract() -> None:
    raw = {
        "errorCode": "0",
        "value": {
            "list": [
                {
                    "lotteryDrawNum": "26124",
                    "lotteryDrawTime": "2026-09-14 00:00:00",
                    "totalSaleAmount": "47,855,820",
                    "totalSaleAmountRj": "21,719,742",
                    "poolBalance": {},
                    "poolBalanceAfterdraw": "123",
                    "prizeLevelList": [
                        {
                            "prizeLevel": "一等奖",
                            "stakeCount": "195",
                            "stakeAmountFormat": "187509",
                            "totalPrizeamount": "36,564,255",
                        },
                        {
                            "prizeLevel": "二等奖",
                            "stakeCount": "5,027",
                            "stakeAmount": "1,827",
                            "totalPrizeamount": "9,184,329",
                        },
                    ],
                    "prizeLevelListRj": [
                        {
                            "prizeLevel": "任选9场",
                            "stakeCount": "19,103",
                            "stakeAmount": "727",
                            "totalPrizeamount": "13,887,881",
                        }
                    ],
                }
            ]
        },
    }
    row = raw["value"]["list"][0]
    economics = parse_official_draw_economics("26124", row, raw_response=raw)

    assert economics.sfc14_sales_yuan == 47855820
    assert economics.choose9_sales_yuan == 21719742
    assert economics.sfc14_first.winning_lines == 195
    assert economics.sfc14_first.prize_per_line_yuan == 187509
    assert economics.sfc14_second.winning_lines == 5027
    assert economics.choose9.winning_lines == 19103
    assert economics.pool_balance_before_yuan is None
    assert economics.pool_balance_after_yuan == 123
    assert economics.raw_response_sha256

    with TemporaryDirectory() as tmp:
        path = write_draw_economics_snapshot(Path(tmp) / "26124.json", economics, raw)
        saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["schema"] == DRAW_ECONOMICS_SCHEMA
    assert saved["economics"]["sfc14_first"]["winning_lines"] == 195
    assert saved["raw_response"] == raw
