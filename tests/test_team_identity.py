import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_lottery_agent.team_identity import (
    configure_team_identity,
    identity_summary,
    normalize_team_name,
    provider_team_match_score,
    register_team_alias,
    team_match_score,
)


class TeamIdentityTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_team_identity(None)

    def test_normalization_transliterates_common_latin_diacritics(self) -> None:
        self.assertEqual(normalize_team_name("BK Häcken"), "bk hacken")
        self.assertEqual(normalize_team_name("Łódź & Sønderjyske"), "lodz sonderjyske")

    def test_only_safe_club_suffixes_receive_partial_score(self) -> None:
        self.assertEqual(team_match_score("比利亚雷亚尔", "Villarreal CF"), 0.8)
        self.assertEqual(team_match_score("瑞典", "Sweden Women"), 0.0)
        self.assertEqual(team_match_score("乌兹别克", "Uzbekistan U20"), 0.0)

    def test_learned_alias_and_provider_id_survive_reload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "team_identity.json"
            configure_team_identity(path)

            changed = register_team_alias(
                "测试新队",
                "Novel City FC",
                provider="fotmob",
                provider_id=7123,
                confidence=0.95,
                source="test_fixture",
            )

            self.assertTrue(changed)
            self.assertTrue(path.exists())
            configure_team_identity(path)
            self.assertEqual(provider_team_match_score("测试新队", "Renamed City", "fotmob", 7123), 1.0)
            self.assertEqual(team_match_score("测试新队", "Novel City FC"), 1.0)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["teams"]["测试新队"]["provider_ids"]["fotmob"], "7123")

    def test_provider_id_cannot_be_owned_by_two_teams(self) -> None:
        with TemporaryDirectory() as temp_dir:
            configure_team_identity(Path(temp_dir) / "team_identity.json")
            register_team_alias("甲队", "Alpha FC", provider="sofascore", provider_id=88)
            register_team_alias("乙队", "Beta FC", provider="sofascore", provider_id=88)
            register_team_alias("甲队", "Wrong Alpha", provider="sofascore", provider_id=99)

            self.assertEqual(identity_summary("甲队")["provider_ids"]["sofascore"], "88")
            self.assertNotIn("sofascore", identity_summary("乙队")["provider_ids"])
            self.assertNotIn("Wrong Alpha", identity_summary("甲队")["aliases"])

    def test_load_removes_kickoff_only_alias_that_conflicts_with_seed_identity(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "team_identity.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "teams": {
                            "巴黎": {
                                "aliases": [
                                    {
                                        "name": "Rennes",
                                        "provider": "fotmob",
                                        "source": "unique_competition_kickoff",
                                    }
                                ],
                                "provider_ids": {"fotmob": "9851"},
                            },
                            "雷恩": {
                                "aliases": [
                                    {
                                        "name": "PSG",
                                        "provider": "fotmob",
                                        "source": "unique_competition_kickoff",
                                    }
                                ],
                                "provider_ids": {"fotmob": "9847"},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            configure_team_identity(path)

            self.assertEqual(team_match_score("巴黎", "PSG"), 1.0)
            self.assertEqual(team_match_score("雷恩", "Rennes"), 1.0)
            self.assertEqual(team_match_score("巴黎", "Rennes"), 0.0)
            self.assertEqual(provider_team_match_score("巴黎", "Rennes", "fotmob", 9851), 0.0)
            cleaned = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("fotmob", cleaned["teams"]["巴黎"]["provider_ids"])
            self.assertNotIn("fotmob", cleaned["teams"]["雷恩"]["provider_ids"])


if __name__ == "__main__":
    unittest.main()
