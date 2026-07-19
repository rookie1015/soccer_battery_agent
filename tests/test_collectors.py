import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent.collectors import (
    NewsItem,
    RawMatch,
    _media_item_matches_match,
    _parse_rss,
    fetch_sina_sfc,
    fetch_sporttery_issue_metadata,
    infer_signals,
    load_matches,
    load_seed_matches,
    search_web_news,
)


class CollectorTests(unittest.TestCase):
    def test_fetch_sina_sfc_rejects_table_from_another_issue(self) -> None:
        html = """
        <input type="hidden" name="num" value="26087">
        <table class="sfcPubTable"><tbody>
          <tr><td>1</td><td>联赛</td><td>06-21 01:00</td><td>主队</td><td>-</td><td>客队</td>
          <td><input name="2608801[1]" value="3"></td></tr>
        </tbody></table>
        """
        with patch("football_lottery_agent.collectors._fetch_text", return_value=html):
            with self.assertRaisesRegex(ValueError, "table belongs to issue 26088"):
                fetch_sina_sfc(Path("data/cache"), issue="26087")

    def test_load_seed_matches(self) -> None:
        matches = load_seed_matches("data/seed_matches.csv")

        self.assertEqual(len(matches), 14)
        self.assertEqual(matches[0].seq, 1)
        self.assertEqual(matches[0].home, "曼城")

    def test_infer_signals_uses_recent_form(self) -> None:
        match = load_seed_matches("data/seed_matches.csv")[0]
        signals = infer_signals(match, ["主队伤停", "赛程密集"])

        self.assertIn("home_form", signals)
        self.assertGreater(signals["home_injury_impact"], 0)

    def test_parse_mainstream_rss_item(self) -> None:
        xml = """<?xml version="1.0"?><rss><channel><item><title>Portugal team news</title><link>https://example.test/a</link><pubDate>today</pubDate></item></channel></rss>"""
        items = _parse_rss(xml)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Portugal team news")
        self.assertEqual(items[0].link, "https://example.test/a")

    def test_search_web_news_uses_google_news_when_primary_indexes_are_empty(self) -> None:
        fallback = [NewsItem(title="Weather disrupted match", link="https://example.test/weather")]
        with (
            patch("football_lottery_agent.collectors._fetch_bing_news", return_value=[]),
            patch("football_lottery_agent.collectors._fetch_google_news", return_value=fallback),
        ):
            items = search_web_news("team weather", Path("data/cache"))

        self.assertEqual(items, fallback)

    def test_media_item_matches_chinese_team_alias(self) -> None:
        match = RawMatch(seq=1, kickoff="", league="世界杯", home="葡萄牙", away="乌兹别克")
        item = NewsItem(title="ESPN Soccer：Portugal face Uzbekistan in World Cup preview", link="")

        self.assertTrue(_media_item_matches_match(match, item))

    @patch("football_lottery_agent.collectors.fetch_sina_sfc", return_value=("26087", []))
    def test_load_matches_passes_requested_issue_to_sina(self, fetch_sina_sfc_mock) -> None:
        load_matches("sina", None, Path("data/cache"), issue="26087")

        fetch_sina_sfc_mock.assert_called_once_with(Path("data/cache"), issue="26087")

    @patch("football_lottery_agent.collectors._fetch_text")
    def test_fetch_sina_sfc_uses_requested_issue_url(self, fetch_text_mock) -> None:
        fetch_text_mock.return_value = '<input name="num" value="26088">'

        with self.assertRaisesRegex(ValueError, "returned issue 26088"):
            fetch_sina_sfc(Path("data/cache"), issue="26087")

        self.assertEqual(fetch_text_mock.call_args.args[0], "https://view.lottery.sina.com.cn/lottery_index/sfc/index?num=26087")

    @patch("football_lottery_agent.collectors._fetch_text")
    def test_fetch_sporttery_issue_metadata_reads_official_sale_endtime(self, fetch_text_mock) -> None:
        fetch_text_mock.return_value = (
            '{"errorCode":"0","value":{"sfcMatch":{"lotteryDrawNum":"26090",'
            '"lotterySaleBegintime":"2026-07-01 09:00:00",'
            '"lotterySaleEndtime":"2026-07-04 23:00:00"}}}'
        )

        metadata = fetch_sporttery_issue_metadata("26090", Path("data/cache"))

        self.assertEqual(metadata["purchase_deadline"], "2026-07-04 23:00:00")
        self.assertEqual(metadata["purchase_deadline_source"], "中国体彩网官方")
        self.assertEqual(metadata["sale_begin_time"], "2026-07-01 09:00:00")

    @patch("football_lottery_agent.collectors._fetch_text")
    def test_fetch_sporttery_issue_metadata_checks_closed_sale_status(self, fetch_text_mock) -> None:
        fetch_text_mock.side_effect = [
            '{"errorCode":"0","value":{"sfcMatch":{}}}',
            '{"errorCode":"0","value":{"sfcMatch":{}}}',
            '{"errorCode":"0","value":{"sfcMatch":{"lotteryDrawNum":"26089",'
            '"lotterySaleEndtime":"2026-06-29 22:00:00"}}}',
        ]

        metadata = fetch_sporttery_issue_metadata("26089", Path("data/cache"))

        self.assertEqual(metadata["purchase_deadline"], "2026-06-29 22:00:00")

    @patch("football_lottery_agent.polymarket.fetch_polymarket_signals_for_matches", return_value={})
    @patch("football_lottery_agent.collectors.fetch_sporttery_issue_metadata", return_value={})
    @patch("football_lottery_agent.collectors._fetch_sina_details", return_value={})
    @patch("football_lottery_agent.collectors._fetch_mainstream_media_briefings", return_value={})
    @patch("football_lottery_agent.collectors._fetch_briefings", return_value={})
    @patch("football_lottery_agent.collectors.load_matches")
    def test_collect_issue_fetches_polymarket_only_for_full_context(
        self,
        load_matches_mock,
        _briefings_mock,
        _media_mock,
        _sina_mock,
        _metadata_mock,
        polymarket_mock,
    ) -> None:
        load_matches_mock.return_value = (
            "26090",
            [RawMatch(seq=index, kickoff="2026-07-05T01:00:00", league="世界杯", home=f"主队{index}", away=f"客队{index}") for index in range(1, 15)],
        )

        with TemporaryDirectory() as tmp:
            collect_path = Path(tmp) / "issue.json"
            from football_lottery_agent.collectors import collect_issue

            collect_issue(collect_path, issue="26090", cache_dir=Path(tmp) / "cache", skip_context_fetches=False)
            collect_issue(collect_path, issue="26090", cache_dir=Path(tmp) / "cache", skip_context_fetches=True)

        self.assertEqual(polymarket_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
