from tempfile import TemporaryDirectory

from football_lottery_agent.standalone_api import run_get_purchase, run_save_purchase


def test_purchase_api_saves_and_reads_record() -> None:
    with TemporaryDirectory() as tmp:
        response = run_save_purchase(
            {
                "issue": "26124",
                "status": "purchased",
                "tickets": [
                    {"play_type": "choose9", "lines": ["3-3-3-3-3-3-3-3-3"]}
                ],
            },
            tmp,
        )
        loaded = run_get_purchase({"issue": "26124"}, tmp)

    assert response["ok"] is True
    assert loaded["purchase"] == response["purchase"]
