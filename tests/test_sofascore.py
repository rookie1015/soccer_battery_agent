import urllib.error
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from football_lottery_agent.collectors import RawMatch
from football_lottery_agent.sofascore import (
    SofaScoreClient,
    _xg_from_shotmap,
    _xg_from_statistics,
    build_sofascore_for_matches,
)


class SofaScoreTests(unittest.TestCase):
    def test_extracts_expected_goals_from_statistics(self) -> None:
        payload = {
            "statistics": [
                {
                    "period": "ALL",
                    "groups": [
                        {
                            "statisticsItems": [
                                {"name": "Ball possession", "home": "52%", "away": "48%"},
                                {"name": "Expected goals", "home": "1.76", "away": "0.84"},
                            ]
                        }
                    ],
                }
            ]
        }

        self.assertEqual(_xg_from_statistics(payload), (1.76, 0.84))

    def test_shotmap_is_used_as_xg_fallback(self) -> None:
        payload = {
            "shotmap": [
                {"isHome": True, "xg": 0.4},
                {"isHome": True, "expectedGoals": 0.3},
                {"isHome": False, "xg": 0.2},
            ]
        }

        self.assertEqual(_xg_from_shotmap(payload), (0.7, 0.2))

    def test_builds_time_weighted_profiles_for_matched_fixture(self) -> None:
        fixture = {
            "id": 900,
            "homeTeam": {"id": 1, "name": "Home FC"},
            "awayTeam": {"id": 2, "name": "Away FC"},
        }
        histories = {
            1: [
                _event(101, 1, 3, 2, 0, 1_720_000_000),
                _event(102, 4, 1, 1, 1, 1_710_000_000),
            ],
            2: [
                _event(201, 5, 2, 1, 1, 1_720_000_000),
                _event(202, 2, 6, 0, 2, 1_710_000_000),
            ],
        }
        xg = {
            101: (1.8, 0.5),
            102: (0.9, 1.0),
            201: (1.1, 1.2),
            202: (0.7, 1.6),
        }

        def fake_fetch(_client, path, _max_age):
            if path.startswith("/sport/football/scheduled-events/"):
                return {"events": [fixture]} if path.endswith("2026-07-26") else {"events": []}
            if path.startswith("/team/"):
                team_id = int(path.split("/")[2])
                return {"events": histories[team_id], "hasNextPage": False}
            if path.endswith("/statistics"):
                event_id = int(path.split("/")[2])
                home, away = xg[event_id]
                return {"statistics": [{"groups": [{"statisticsItems": [{"name": "Expected goals", "home": home, "away": away}]}]}]}
            return None

        match = RawMatch(
            seq=1,
            kickoff="2026-07-26T20:00:00",
            league="测试联赛",
            home="Home FC",
            away="Away FC",
        )
        score = lambda local, candidate: 1.0 if local == candidate else 0.0
        with (
            TemporaryDirectory() as tmp,
            patch.object(SofaScoreClient, "fetch", autospec=True, side_effect=fake_fetch),
        ):
            result = build_sofascore_for_matches([match], tmp, lookback=8, xg_matches=8, team_score=score)[1]

        self.assertIsNotNone(result.home)
        self.assertIsNotNone(result.away)
        self.assertEqual(result.home.xg_matches_used, 2)
        self.assertEqual(result.away.xg_matches_used, 2)
        self.assertGreater(result.home.xg_for_per_match, result.away.xg_for_per_match)
        self.assertEqual(result.source["matched_event_id"], 900)

    def test_forbidden_response_opens_circuit_and_keeps_calls_bounded(self) -> None:
        error = urllib.error.HTTPError(
            "https://www.sofascore.com/api/v1/test",
            403,
            "Forbidden",
            {},
            None,
        )
        with TemporaryDirectory() as tmp, patch("urllib.request.urlopen", side_effect=error) as urlopen:
            client = SofaScoreClient(Path(tmp))

            self.assertIsNone(client.fetch("/test", 60))
            self.assertIsNone(client.fetch("/another", 60))

        self.assertTrue(client.blocked)
        self.assertEqual(urlopen.call_count, 1)


def _event(
    event_id: int,
    home_id: int,
    away_id: int,
    home_score: int,
    away_score: int,
    timestamp: int,
) -> dict:
    return {
        "id": event_id,
        "startTimestamp": timestamp,
        "status": {"type": "finished"},
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "homeScore": {"current": home_score},
        "awayScore": {"current": away_score},
    }


if __name__ == "__main__":
    unittest.main()
