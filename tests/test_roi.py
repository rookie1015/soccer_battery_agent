from pathlib import Path
from tempfile import TemporaryDirectory

from football_lottery_agent.roi import (
    calculate_actual_purchase_roi,
    calculate_report_roi,
    summarize_dual_roi,
    summarize_latest_issue_roi,
    write_roi_backtest,
)


def _report(issue: str, *, cost: int, choose9_cost: int, prize: int) -> dict[str, object]:
    return {
        "issue": issue,
        "budget": {"total_cost_yuan": cost},
        "choose9": {"cost_yuan": choose9_cost},
        "prize": {"status": "published", "total_prize_yuan": prize},
    }


def test_roi_includes_both_independent_ticket_costs() -> None:
    roi = calculate_report_roi(_report("26124", cost=500, choose9_cost=200, prize=1827))

    assert roi["total_cost_yuan"] == 700
    assert roi["net_profit_yuan"] == 1127
    assert roi["roi_percent"] == 161.0
    assert roi["cost_source"] == "saved_budget"
    assert roi["included_games"] == ("sfc14", "choose9")


def test_roi_infers_legacy_rectangular_sfc14_cost() -> None:
    report = {
        "issue": "26087",
        "predictions": [
            {"picks": ["3", "1"] if seq == 1 else ["3"]}
            for seq in range(1, 15)
        ],
        "prize": {"status": "published", "total_prize_yuan": 100},
    }

    roi = calculate_report_roi(report, provenance="legacy_markdown_review")

    assert roi["status"] == "complete"
    assert roi["sfc14_cost_yuan"] == 4
    assert roi["choose9_cost_yuan"] == 0
    assert roi["net_profit_yuan"] == 96
    assert roi["cost_source"] == "inferred_rectangular_ticket"
    assert roi["included_games"] == ("sfc14",)


def test_roi_rejects_legacy_line_portfolio_with_unknown_cost() -> None:
    report = {
        "issue": "26110",
        "legacy_line_portfolio_cost_unknown": True,
        "predictions": [{"picks": ["3", "1", "0"]} for _ in range(14)],
        "prize": {
            "status": "published",
            "sfc14": {"total_prize_yuan": 1938},
            "choose9": {"total_prize_yuan": 414},
            "total_prize_yuan": 2352,
        },
    }

    roi = calculate_report_roi(report, provenance="legacy_markdown_review")

    assert roi["status"] == "incomplete_cost"
    assert roi["gross_prize_yuan"] == 1938
    assert roi["cost_source"] == "unknown"


def test_roi_backtest_uses_only_latest_review_per_issue_and_measures_drawdown() -> None:
    entries = [
        {"kind": "review", "issue": "26122", "report": _report("26122", cost=100, choose9_cost=0, prize=0)},
        {"kind": "review", "issue": "26121", "report": _report("26121", cost=100, choose9_cost=0, prize=300)},
        {"kind": "review", "issue": "26121", "report": _report("26121", cost=999, choose9_cost=0, prize=0)},
    ]
    summary = summarize_latest_issue_roi(entries)

    assert summary["record_count"] == 2
    assert summary["total_cost_yuan"] == 200
    assert summary["gross_prize_yuan"] == 300
    assert summary["net_profit_yuan"] == 100
    assert summary["max_drawdown_yuan"] == 100

    with TemporaryDirectory() as tmp:
        markdown, payload = write_roi_backtest(summary, Path(tmp) / "roi.md")
        assert "历史票面ROI回测" in markdown.read_text(encoding="utf-8")
        assert payload.exists()


def test_actual_purchase_roi_uses_actual_lines_and_never_recommendation_cost() -> None:
    report = {
        "issue": "26124",
        "predictions": [
            {"seq": seq, "final_result": "3" if seq != 14 else "1"}
            for seq in range(1, 15)
        ],
        "prize": {
            "status": "published",
            "sfc14": {"first_prize_per_line_yuan": 1000, "second_prize_per_line_yuan": 50},
            "choose9": {"prize_per_line_yuan": 20},
        },
    }
    purchase = {
        "status": "purchased",
        "actual_amount_yuan": 2,
        "tickets": [
            {
                "play_type": "sfc14",
                "cost_yuan": 2,
                "lines": [{"sequences": list(range(1, 15)), "outcomes": ["3"] * 14}],
            }
        ],
    }

    roi = calculate_actual_purchase_roi(report, purchase)

    assert roi["total_cost_yuan"] == 2
    assert roi["gross_prize_yuan"] == 50
    assert roi["net_profit_yuan"] == 48
    assert roi["scope"] == "actual_purchase"


def test_dual_roi_keeps_missing_actual_purchases_out_of_actual_totals() -> None:
    entries = [{"kind": "review", "issue": "26124", "report": _report("26124", cost=100, choose9_cost=0, prize=0)}]
    dual = summarize_dual_roi(entries)

    assert dual["recommendation_replay"]["total_cost_yuan"] == 100
    assert dual["actual_purchase"]["total_cost_yuan"] is None
    assert dual["actual_purchase"]["roi_percent"] is None
    assert dual["actual_purchase"]["no_purchase_record_count"] == 1
