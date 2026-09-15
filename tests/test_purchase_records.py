from tempfile import TemporaryDirectory

import pytest

from football_lottery_agent.purchase_records import load_purchase_record, save_purchase_record


def test_purchase_record_round_trip_with_exact_actual_lines() -> None:
    with TemporaryDirectory() as tmp:
        saved = save_purchase_record(
            tmp,
            {
                "issue": "26124",
                "status": "purchased",
                "actual_amount_yuan": 2,
                "tickets": [{"play_type": "sfc14", "lines": ["3-1-0-3-1-0-3-1-0-3-1-0-3-1"]}],
            },
        )
        loaded = load_purchase_record(tmp, "26124")

    assert loaded == saved
    assert saved["actual_purchase_confirmed"] is True
    assert saved["amount_matches_ticket_cost"] is True


def test_not_purchased_cannot_claim_an_amount() -> None:
    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="未购买"):
            save_purchase_record(
                tmp,
                {"issue": "26124", "status": "not_purchased", "actual_amount_yuan": 2},
            )
