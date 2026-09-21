import unittest

from football_lottery_agent.league_team_aliases import (
    ASIAN_CUP_TEAM_COUNTS,
    ASIAN_CUP_TEAM_ROWS,
    EUROPEAN_CUP_TEAM_COUNTS,
    EUROPEAN_CUP_TEAM_ROWS,
    FOTMOB_TEAM_IDS,
    LEAGUE_TEAM_COUNTS,
    LEAGUE_TEAM_ROWS,
    SUPPLEMENTAL_TEAM_ROWS,
)
from football_lottery_agent.strength_model import FOTMOB_LEAGUE_ALIASES
from football_lottery_agent.team_identity import (
    configure_team_identity,
    provider_team_match_score,
    team_match_score,
)


class LeagueTeamAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_team_identity(None)

    def tearDown(self) -> None:
        configure_team_identity(None)

    def test_current_rosters_have_expected_team_counts(self) -> None:
        self.assertEqual(
            LEAGUE_TEAM_COUNTS,
            {
                "英超": 20,
                "德甲": 18,
                "意甲": 20,
                "西甲": 20,
                "法甲": 18,
                "荷甲": 18,
                "葡超": 18,
                "法乙": 18,
                "瑞典超": 16,
                "芬超": 12,
                "瑞士超": 12,
                "美职": 30,
            },
        )
        self.assertEqual(sum(LEAGUE_TEAM_COUNTS.values()), 220)

    def test_every_seed_team_matches_its_fotmob_name_and_id(self) -> None:
        seen_ids: set[str] = set()
        for rows in LEAGUE_TEAM_ROWS.values():
            for local_name, team_id, aliases in rows:
                with self.subTest(local_name=local_name):
                    self.assertTrue(aliases)
                    self.assertEqual(team_match_score(local_name, aliases[0]), 1.0)
                    self.assertEqual(
                        provider_team_match_score(local_name, "renamed", "fotmob", team_id),
                        1.0,
                    )
                    self.assertNotIn(str(team_id), seen_ids)
                    seen_ids.add(str(team_id))
        self.assertGreaterEqual(len(FOTMOB_TEAM_IDS), 220 + len(SUPPLEMENTAL_TEAM_ROWS))

    def test_current_european_cup_rosters_are_complete_and_matchable(self) -> None:
        self.assertEqual(
            EUROPEAN_CUP_TEAM_COUNTS,
            {"欧冠": 36, "欧联": 36, "欧协联": 36},
        )
        for competition, rows in EUROPEAN_CUP_TEAM_ROWS.items():
            seen_ids: set[str] = set()
            for local_name, team_id, aliases in rows:
                with self.subTest(competition=competition, local_name=local_name):
                    self.assertTrue(aliases)
                    self.assertEqual(team_match_score(local_name, aliases[0]), 1.0)
                    self.assertEqual(
                        provider_team_match_score(local_name, "renamed", "fotmob", team_id),
                        1.0,
                    )
                    self.assertNotIn(str(team_id), seen_ids)
                    seen_ids.add(str(team_id))

    def test_current_asian_cup_rosters_are_complete_and_matchable(self) -> None:
        self.assertEqual(
            ASIAN_CUP_TEAM_COUNTS,
            {"亚冠精英": 32, "亚冠二级": 32},
        )
        for competition, rows in ASIAN_CUP_TEAM_ROWS.items():
            seen_ids: set[str] = set()
            for local_name, team_id, aliases in rows:
                with self.subTest(competition=competition, local_name=local_name):
                    self.assertTrue(aliases)
                    self.assertEqual(team_match_score(local_name, aliases[0]), 1.0)
                    self.assertEqual(
                        provider_team_match_score(local_name, "renamed", "fotmob", team_id),
                        1.0,
                    )
                    self.assertNotIn(str(team_id), seen_ids)
                    seen_ids.add(str(team_id))

    def test_common_asian_cup_chinese_variants_resolve(self) -> None:
        pairs = {
            "柔佛": "Johor Darul Ta'zim",
            "迪拜国民": "Shabab Al-Ahli Dubai FC",
            "上海上港": "Shanghai Port",
            "全北现代汽车": "Jeonbuk Hyundai Motors FC",
            "The Cong - Viettel FC": "Viettel",
            "Wofoo Tai Po": "Tai Po",
        }
        for local_name, provider_name in pairs.items():
            with self.subTest(local_name=local_name):
                self.assertEqual(team_match_score(local_name, provider_name), 1.0)

    def test_common_european_cup_chinese_variants_resolve(self) -> None:
        pairs = {
            "AEK雅典": "AEK Athens",
            "沙巴巴库": "Sabah FK",
            "斯拉维亚": "Slavia Prague",
            "费伦茨": "Ferencváros",
            "利勒斯": "Lillestrøm",
            "赫塔菲": "Getafe",
            "帕福斯": "Pafos FC",
            "阿拉木图": "Kairat Almaty",
        }
        for local_name, provider_name in pairs.items():
            with self.subTest(local_name=local_name):
                self.assertEqual(team_match_score(local_name, provider_name), 1.0)

    def test_previously_missing_26123_teams_are_seeded(self) -> None:
        pairs = {
            "阿斯顿维拉": "Aston Villa",
            "诺丁汉森林": "Nottingham Forest",
            "奥格斯堡": "Augsburg",
            "勒沃库森": "Bayer Leverkusen",
            "科隆": "1. FC Köln",
            "不莱梅": "Werder Bremen",
            "拉齐奥": "Lazio",
            "AC米兰": "Milan",
        }
        for local_name, provider_name in pairs.items():
            with self.subTest(local_name=local_name):
                self.assertEqual(team_match_score(local_name, provider_name), 1.0)

    def test_previously_missing_26125_teams_are_seeded(self) -> None:
        pairs = {
            "纽卡斯尔联": ("Newcastle United", 10261),
            "吉达国民": ("Al Ahli", 2530),
            "塔什干棉农": ("Pakhtakor Tashkent", 102141),
            "佐加顿斯": ("Djurgården", 9802),
            "哥德堡盖斯": ("GAIS", 8297),
            "博德闪耀": ("Bodø/Glimt", 8402),
            "桑德菲杰": ("Sandefjord", 8609),
            "中国女足": ("China (W)", 5904),
            "中国香港女足": ("Hong Kong (W)", 623229),
        }
        for local_name, (provider_name, provider_id) in pairs.items():
            with self.subTest(local_name=local_name):
                self.assertEqual(team_match_score(local_name, provider_name), 1.0)
                self.assertEqual(
                    provider_team_match_score(local_name, "renamed", "fotmob", provider_id),
                    1.0,
                )

    def test_league_name_variants_are_supported(self) -> None:
        self.assertIn("allsvenskan", FOTMOB_LEAGUE_ALIASES["瑞超"])
        self.assertIn("allsvenskan", FOTMOB_LEAGUE_ALIASES["瑞典超"])
        self.assertIn("swiss super league", FOTMOB_LEAGUE_ALIASES["瑞士超"])
        self.assertIn("mls", FOTMOB_LEAGUE_ALIASES["美职联"])
        self.assertIn("afc champions league elite west", FOTMOB_LEAGUE_ALIASES["亚冠精英"])
        self.assertIn("afc champions league elite east", FOTMOB_LEAGUE_ALIASES["亚冠"])
        self.assertIn("afc champions league two", FOTMOB_LEAGUE_ALIASES["亚冠二级"])
        self.assertIn("conference league", FOTMOB_LEAGUE_ALIASES["欧协联"])


if __name__ == "__main__":
    unittest.main()
