from pathlib import Path
from tempfile import TemporaryDirectory

from football_lottery_agent.roi import (
    calculate_report_roi,
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
