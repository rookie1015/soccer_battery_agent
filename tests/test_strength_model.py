import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_lottery_agent.strength_model import (
    _estimate_starting_eleven,
    _has_injury,
    _player_strength,
    _player_value,
    _rating,
    _learn_one_sided_provider_aliases,
    _learn_unique_context_provider_aliases,
    _match_fotmob_event,
    _team_score,
)
from football_lottery_agent.collectors import RawMatch
from football_lottery_agent.team_identity import TEAM_ALIASES, configure_team_identity, normalize_team_name


class StrengthModelTests(unittest.TestCase):
    def test_team_score_uses_aliases(self) -> None:
        self.assertEqual(_team_score("荷兰", "Netherlands"), 1.0)
        self.assertEqual(_team_score("热刺", "Tottenham Hotspur"), 1.0)
        self.assertEqual(_team_score("赫根", "Häcken"), 1.0)
        self.assertEqual(_team_score("迈阿密国际", "Inter Miami CF"), 1.0)

    def test_team_normalization_does_not_delete_chinese_names(self) -> None:
        self.assertEqual(normalize_team_name("圣路易斯城"), "圣路易斯城")

    def test_fixture_pairing_learns_unknown_opponent_from_known_side(self) -> None:
        local = "测试新队"
        match = RawMatch(
            seq=1,
            kickoff="2026-08-02T18:00:00+08:00",
            league="测试联赛",
            home="赫根",
            away=local,
        )
        events = {
            "20260802": [{"home": {"name": "Häcken"}, "away": {"name": "Novel City FC"}}]
        }
        try:
            _learn_one_sided_provider_aliases([match], events)
            self.assertEqual(_team_score(local, "Novel City FC"), 1.0)
        finally:
            TEAM_ALIASES.pop(local, None)

    def test_reversed_provider_fixture_is_reported_for_safe_side_mapping(self) -> None:
        match = RawMatch(
            seq=1,
            kickoff="2026-08-02T18:00:00+08:00",
            league="测试联赛",
            home="赫根",
            away="卡尔马",
        )
        events = {
            "20260802": [
                {
                    "id": 99,
                    "home": {"id": 2, "name": "Kalmar FF"},
                    "away": {"id": 1, "name": "Häcken"},
                }
            ]
        }

        event, reversed_sides, diagnostic = _match_fotmob_event(match, events)

        self.assertEqual(event["id"], 99)
        self.assertTrue(reversed_sides)
        self.assertEqual(diagnostic["match_status"], "matched")

    def test_unique_competition_and_kickoff_bootstraps_two_unknown_names(self) -> None:
        match = RawMatch(
            seq=1,
            kickoff="2026-08-07T01:45:00+08:00",
            league="欧罗巴",
            home="测试甲队",
            away="测试乙队",
        )
        events = {
            "20260806": [
                {
                    "id": 101,
                    "_provider_league_name": "Europa League Qualification",
                    "status": {"utcTime": "2026-08-06T17:45:00Z"},
                    "home": {"id": 11, "name": "Alpha Town"},
                    "away": {"id": 12, "name": "Beta City"},
                },
                {
                    "id": 102,
                    "_provider_league_name": "Conference League Qualification",
                    "status": {"utcTime": "2026-08-06T17:45:00Z"},
                    "home": {"id": 21, "name": "Wrong Home"},
                    "away": {"id": 22, "name": "Wrong Away"},
                },
            ]
        }
        with TemporaryDirectory() as temp_dir:
            configure_team_identity(Path(temp_dir) / "team_identity.json")
            _learn_unique_context_provider_aliases([match], events)
            self.assertEqual(_team_score("测试甲队", "Alpha Town"), 1.0)
            self.assertEqual(_team_score("测试乙队", "Beta City"), 1.0)
        configure_team_identity(None)

    def test_same_time_competition_group_is_not_guessed(self) -> None:
        matches = [
            RawMatch(1, "2026-08-05T00:00:00+08:00", "欧冠", "未知甲", "未知乙"),
            RawMatch(2, "2026-08-05T00:00:00+08:00", "欧冠", "未知丙", "未知丁"),
        ]
        events = {
            "20260804": [
                {
                    "id": event_id,
                    "_provider_league_name": "Champions League Qualification",
                    "status": {"utcTime": "2026-08-04T16:00:00Z"},
                    "home": {"id": event_id * 10, "name": f"Home {event_id}"},
                    "away": {"id": event_id * 10 + 1, "name": f"Away {event_id}"},
                }
                for event_id in (1, 2)
            ]
        }
        with TemporaryDirectory() as temp_dir:
            configure_team_identity(Path(temp_dir) / "team_identity.json")
            _learn_unique_context_provider_aliases(matches, events)
            self.assertEqual(_team_score("未知甲", "Home 1"), 0.0)
            self.assertEqual(_team_score("未知丙", "Home 2"), 0.0)
        configure_team_identity(None)

    def test_rating_is_bounded(self) -> None:
        self.assertGreater(_rating(0.7, 0.2, 2.0, 0.8, 1.9, 0.9), 0.5)
        self.assertLessEqual(_rating(1.0, 0.0, 5.0, 0.0, 5.0, 0.0), 1.0)

    def test_estimated_eleven_prefers_value_with_position_balance(self) -> None:
        players = [
            {"id": 1, "positionId": 0, "transferValue": 1_000_000},
            *[{"id": 10 + index, "positionId": 1, "transferValue": (index + 1) * 1_000_000} for index in range(5)],
            *[{"id": 20 + index, "positionId": 2, "transferValue": (index + 1) * 1_000_000} for index in range(4)],
            *[{"id": 30 + index, "positionId": 3, "transferValue": (index + 1) * 1_000_000} for index in range(4)],
        ]

        eleven = _estimate_starting_eleven(players)

        self.assertEqual(len(eleven), 11)
        self.assertEqual(sum(1 for player in eleven if player["positionId"] == 0), 1)
        self.assertEqual(sum(1 for player in eleven if player["positionId"] == 1), 4)
        self.assertGreater(_player_value(eleven[-1]), 0)

    def test_recent_player_form_adjusts_strength_without_overriding_it(self) -> None:
        player = {"id": 7, "positionId": 3, "transferValue": 30_000_000, "rating": 6.5}

        baseline = _player_strength(player)
        in_form = _player_strength(player, {"7": (6, 8.2)})
        out_of_form = _player_strength(player, {"7": (6, 5.4)})

        self.assertGreater(in_form, baseline)
        self.assertLess(out_of_form, baseline)
        self.assertLess(in_form / baseline, 1.13)

    def test_injury_detection_accepts_structured_api_values(self) -> None:
        self.assertTrue(_has_injury({"description": "Hamstring injury"}))
        self.assertTrue(_has_injury([{"type": "Knock"}]))
        self.assertFalse(_has_injury({"description": None, "active": False}))
        self.assertFalse(_has_injury("none"))
        self.assertFalse(_has_injury(None))


if __name__ == "__main__":
    unittest.main()
