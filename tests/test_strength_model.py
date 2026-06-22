import unittest

from football_lottery_agent.strength_model import _rating, _team_score


class StrengthModelTests(unittest.TestCase):
    def test_team_score_uses_aliases(self) -> None:
        self.assertEqual(_team_score("荷兰", "Netherlands"), 1.0)
        self.assertEqual(_team_score("热刺", "Tottenham Hotspur"), 1.0)

    def test_rating_is_bounded(self) -> None:
        self.assertGreater(_rating(0.7, 0.2, 2.0, 0.8, 1.9, 0.9), 0.5)
        self.assertLessEqual(_rating(1.0, 0.0, 5.0, 0.0, 5.0, 0.0), 1.0)


if __name__ == "__main__":
    unittest.main()
