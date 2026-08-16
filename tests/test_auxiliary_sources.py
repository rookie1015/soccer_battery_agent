import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from football_lottery_agent.auxiliary_sources import (
    AuxiliaryMatch,
    auxiliary_notes,
    auxiliary_odds,
    fetch_500_issue,
    fetch_free_auxiliary_sources,
    fetch_zgzcw_issue,
)


class AuxiliarySourceTests(unittest.TestCase):
    def test_parses_500_issue_rows(self) -> None:
        html = """
        <li class="on"><a data-expect="26106">第26106期</a></li>
        <tr class="bet-tb-tr" data-isend="0" data-cid="1"
            data-vs="伯恩利vs西汉姆联" data-bjpl="2.98,3.38,2.01"
            data-asian="0.84,受平手/半球,0.94">
          <td class="td td-endtime">08-16 23:00</td>
        </tr>
        """
        with patch("football_lottery_agent.auxiliary_sources._fetch_cached_text", return_value=html):
            rows = fetch_500_issue("26106", Path("cache"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].seq, 1)
        self.assertEqual(rows[0].home, "伯恩利")
        self.assertEqual(rows[0].odds, (2.98, 3.38, 2.01))
        self.assertEqual(rows[0].kickoff, "08-16 23:00")

    def test_500_rejects_wrong_selected_issue(self) -> None:
        html = '<li class="on"><a data-expect="26107">第26107期</a></li>'
        with patch("football_lottery_agent.auxiliary_sources._fetch_cached_text", return_value=html):
            with self.assertRaisesRegex(ValueError, "returned issue 26107"):
                fetch_500_issue("26106", Path("cache"))

    def test_parses_zgzcw_issue_rows(self) -> None:
        payload = """{
          "matchInfo": [{
            "issue": "26106", "hostNameFull": "塞尔塔", "guestNameFull": "奥萨苏纳",
            "gameStartDate": "2026-08-28 02:30:00", "europeSp": "2.02 3.35 3.67",
            "yapan": "1.030 半球 0.840", "isStop": "false", "playId": "4565318"
          }]
        }"""
        with patch("football_lottery_agent.auxiliary_sources._fetch_cached_text", return_value=payload):
            rows = fetch_zgzcw_issue("26106", Path("cache"))

        self.assertEqual(rows[0].home, "塞尔塔")
        self.assertEqual(rows[0].kickoff, "2026-08-28 02:30:00")
        self.assertEqual(rows[0].odds, (2.02, 3.35, 3.67))

    def test_issue_specific_sources_match_by_validated_sequence(self) -> None:
        local = [SimpleNamespace(seq=1, home="桑坦德竞技", away="比利亚")]
        five_hundred = AuxiliaryMatch(
            provider="500.com",
            seq=1,
            home="桑坦德",
            away="比利亚雷亚尔",
            kickoff="08-16 23:00",
            odds=(3.25, 3.48, 1.87),
        )
        with (
            patch("football_lottery_agent.auxiliary_sources.fetch_500_issue", return_value=[five_hundred]),
            patch("football_lottery_agent.auxiliary_sources.fetch_zgzcw_issue", return_value=[]),
        ):
            result = fetch_free_auxiliary_sources(local, "26106", Path("cache"))

        self.assertEqual(result.by_seq[1], (five_hundred,))
        self.assertEqual(result.audit["providers"]["500.com"]["matched_matches"], 1)

    def test_auxiliary_odds_fill_only_when_sina_is_missing(self) -> None:
        rows = (
            AuxiliaryMatch("500.com", 1, "主", "客", "", (2.0, 3.0, 4.0)),
            AuxiliaryMatch("zgzcw", 1, "主", "客", "", (2.2, 3.2, 4.2)),
        )

        self.assertEqual(auxiliary_odds(rows), (2.1, 3.1, 4.1))
        self.assertIn("新浪欧赔缺失", auxiliary_notes(rows, None)[0])
        self.assertIn("未覆盖新浪主源", auxiliary_notes(rows, SimpleNamespace(home=4.0, draw=3.2, away=2.0))[0])

    def test_auxiliary_notes_report_schedule_difference_without_overriding_sina(self) -> None:
        rows = (
            AuxiliaryMatch("500.com", 5, "塞尔塔", "奥萨苏纳", "08-17 03:30", (2.0, 3.2, 3.8)),
            AuxiliaryMatch("zgzcw", 5, "塞尔塔", "奥萨苏纳", "2026-08-28 02:30:00", (2.0, 3.2, 3.8)),
        )

        notes = auxiliary_notes(
            rows,
            SimpleNamespace(home=2.0, draw=3.2, away=3.8),
            "2026-08-28T02:30:00+08:00",
        )

        self.assertIn("500网显示08-17 03:30", notes[0])
        self.assertIn("未覆盖新浪主源", notes[0])


if __name__ == "__main__":
    unittest.main()
