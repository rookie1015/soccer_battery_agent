import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent.collectors import RawMatch
from football_lottery_agent.foreign_odds import (
    _fetch_the_odds_api,
    _match_event_to_odds,
    check_the_odds_api_usage,
    fetch_foreign_odds_for_matches,
)


class _FakeResponse:
    def __init__(self, payload: object, headers: dict[str, str]) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class ForeignOddsTests(unittest.TestCase):
    @staticmethod
    def _event() -> dict[str, object]:
        return {
            "id": "evt",
            "home_team": "Netherlands",
            "away_team": "Sweden",
            "commence_time": "2026-06-20T17:00:00Z",
            "bookmakers": [
                {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Netherlands", "price": 1.7},
                    {"name": "Draw", "price": 3.8},
                    {"name": "Sweden", "price": 4.8},
                ]}]},
            ],
        }

    def test_match_event_to_odds_aggregates_bookmakers(self) -> None:
        match = RawMatch(seq=1, kickoff="2026-06-21T01:00:00+08:00", league="世界杯", home="荷兰", away="瑞典")
        events = [
            {
                "id": "evt",
                "home_team": "Netherlands",
                "away_team": "Sweden",
                "commence_time": "2026-06-20T17:00:00Z",
                "bookmakers": [
                    {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                        {"name": "Netherlands", "price": 1.7},
                        {"name": "Draw", "price": 3.8},
                        {"name": "Sweden", "price": 4.8},
                    ]}]},
                    {"key": "betfair", "markets": [{"key": "h2h", "outcomes": [
                        {"name": "Netherlands", "price": 1.8},
                        {"name": "Draw", "price": 3.9},
                        {"name": "Sweden", "price": 4.6},
                    ]}]},
                ],
            }
        ]

        odds = _match_event_to_odds(match, "soccer_fifa_world_cup", events)

        self.assertIsNotNone(odds)
        assert odds is not None
        self.assertEqual(odds.bookmaker_count, 2)
        self.assertEqual(odds.odds.home, 1.75)
        self.assertEqual(odds.odds.draw, 3.85)
        self.assertEqual(odds.odds.away, 4.7)

    def test_fetch_records_live_call_quota_and_then_cache_use(self) -> None:
        match = RawMatch(seq=1, kickoff="2026-06-21T01:00:00+08:00", league="世界杯", home="荷兰", away="瑞典")
        headers = {
            "x-requests-remaining": "494",
            "x-requests-used": "6",
            "x-requests-last": "6",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            live_audit: dict[str, object] = {}
            with patch("urllib.request.urlopen", return_value=_FakeResponse([self._event()], headers)) as urlopen:
                result = fetch_foreign_odds_for_matches(
                    [match],
                    temp_dir,
                    api_key="secret",
                    sport_keys=("soccer_fifa_world_cup",),
                    audit=live_audit,
                )
            self.assertEqual(list(result), [1])
            self.assertEqual(live_audit["status"], "success_live")
            self.assertEqual(live_audit["attempted_queries"], 1)
            self.assertEqual(live_audit["credits_remaining"], 494)
            self.assertEqual(live_audit["credits_last"], 6)
            urlopen.assert_called_once()

            cache_audit: dict[str, object] = {}
            with patch("urllib.request.urlopen") as cached_urlopen:
                cached_result = fetch_foreign_odds_for_matches(
                    [match],
                    temp_dir,
                    api_key="secret",
                    sport_keys=("soccer_fifa_world_cup",),
                    audit=cache_audit,
                )
            self.assertEqual(list(cached_result), [1])
            self.assertEqual(cache_audit["status"], "success_cache")
            self.assertEqual(cache_audit["attempted_queries"], 0)
            self.assertEqual(cache_audit["cache_hits"], 1)
            cached_urlopen.assert_not_called()

    def test_usage_check_reads_quota_without_odds_request(self) -> None:
        headers = {
            "x-requests-remaining": "488",
            "x-requests-used": "12",
            "x-requests-last": "0",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse([{"key": "soccer_epl"}], headers)) as urlopen:
            usage = check_the_odds_api_usage("secret")

        self.assertEqual(usage["status"], "valid")
        self.assertEqual(usage["credits_remaining"], 488)
        self.assertEqual(usage["credits_used"], 12)
        self.assertEqual(usage["credits_last"], 0)
        self.assertEqual(usage["active_sports"], 1)
        request = urlopen.call_args.args[0]
        self.assertIn("/v4/sports/", request.full_url)
        self.assertNotIn("/odds", request.full_url)

    def test_fetch_reports_exhausted_usage_credits(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.invalid",
            401,
            "Unauthorized",
            {"x-requests-remaining": "0", "x-requests-used": "500"},
            io.BytesIO(json.dumps({"error_code": "OUT_OF_USAGE_CREDITS"}).encode("utf-8")),
        )
        audit: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as temp_dir, patch("urllib.request.urlopen", side_effect=error):
            events = _fetch_the_odds_api(
                "soccer_epl",
                "secret",
                "uk,eu",
                "",
                Path(temp_dir),
                audit=audit,
            )
        self.assertEqual(events, [])
        self.assertEqual(audit["status"], "out_of_credits")
        self.assertTrue(audit["live_attempted"])
        self.assertEqual(audit["credits_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
