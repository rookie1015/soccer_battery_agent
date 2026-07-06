from football_lottery_agent.collectors import RawMatch
from football_lottery_agent.polymarket import _match_market_to_signal


def test_match_market_to_signal_reads_probabilities() -> None:
    match = RawMatch(seq=1, kickoff="", league="世界杯", home="葡萄牙", away="乌兹别克")
    markets = [
        {
            "id": "1",
            "question": "Portugal vs Uzbekistan: who will win this World Cup match?",
            "slug": "portugal-vs-uzbekistan-world-cup",
            "description": "Soccer market for Portugal against Uzbekistan.",
            "outcomes": '["Portugal", "Draw", "Uzbekistan"]',
            "outcomePrices": '["0.62", "0.25", "0.13"]',
            "volume": "12500.5",
            "liquidity": "900",
        }
    ]

    signal = _match_market_to_signal(match, markets)

    assert signal is not None
    assert signal.question == "Portugal vs Uzbekistan: who will win this World Cup match?"
    assert signal.probability_summary == "Portugal 62%，Draw 25%，Uzbekistan 13%"
    assert signal.raw["outcome_prices"] == [0.62, 0.25, 0.13]


def test_match_market_to_signal_ignores_non_soccer_market() -> None:
    match = RawMatch(seq=1, kickoff="", league="世界杯", home="葡萄牙", away="乌兹别克")
    markets = [
        {
            "question": "Portugal GDP growth above 2%?",
            "description": "Economic market, not football.",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.4", "0.6"]',
        }
    ]

    assert _match_market_to_signal(match, markets) is None
