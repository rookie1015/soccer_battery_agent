import unittest

from football_lottery_agent.collectors import RawMatch
from football_lottery_agent.foreign_odds import _match_event_to_odds


class ForeignOddsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
