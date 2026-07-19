import unittest
from unittest.mock import patch

from football_lottery_agent.collectors import NewsItem
from football_lottery_agent.loader import load_issue
from football_lottery_agent.post_match_context import find_post_match_evidence
from football_lottery_agent.review import MatchResult, build_review
from football_lottery_agent.strategy import build_ticket_plan


class PostMatchContextTests(unittest.TestCase):
    def test_finds_injury_evidence_only_for_a_missed_match(self) -> None:
        plan = build_ticket_plan(load_issue("data/sample_issue.json"))
        target = next(prediction for prediction in plan.predictions if "0" not in prediction.picks)
        results = {
            prediction.match.seq: MatchResult(prediction.match.seq, 1, 0)
            for prediction in plan.predictions
        }
        results[target.match.seq] = MatchResult(target.match.seq, 0, 1)
        report = build_review(plan, results)

        with patch(
            "football_lottery_agent.post_match_context.search_web_news",
            return_value=[NewsItem("Key player injured before the match", "https://example.test/injury")],
        ):
            evidence = find_post_match_evidence(report, "data/cache/test-post-match")

        self.assertIn(target.match.seq, evidence)
        self.assertEqual(evidence[target.match.seq][0]["label"], "关键伤停或临场阵容变化")
        self.assertEqual(evidence[target.match.seq][0]["sources"][0]["url"], "https://example.test/injury")


if __name__ == "__main__":
    unittest.main()
