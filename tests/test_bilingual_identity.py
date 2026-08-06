import unittest
from pathlib import Path
from unittest.mock import patch

from football_lottery_agent.bilingual_identity import _club_alias_variants, fetch_dbpedia_club_aliases


class BilingualIdentityTests(unittest.TestCase):
    def test_dbpedia_club_suffixes_are_removed_for_provider_matching(self) -> None:
        self.assertEqual(_club_alias_variants("Swansea City A.F.C."), ("Swansea City A.F.C.", "Swansea City"))
        self.assertEqual(_club_alias_variants("Portsmouth F.C."), ("Portsmouth F.C.", "Portsmouth"))

    def test_bilingual_lookup_extracts_english_label_variants(self) -> None:
        payload = {
            "results": {
                "bindings": [
                    {"en": {"type": "literal", "xml:lang": "en", "value": "Derby County F.C."}}
                ]
            }
        }
        with patch("football_lottery_agent.bilingual_identity._fetch_json", return_value=payload):
            aliases = fetch_dbpedia_club_aliases("德比郡", Path("unused"))
        self.assertEqual(aliases, ("Derby County F.C.", "Derby County"))


if __name__ == "__main__":
    unittest.main()
