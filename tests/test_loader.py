import tempfile
import unittest
from pathlib import Path

from football_lottery_agent.loader import load_issue


class LoaderTests(unittest.TestCase):
    def test_load_issue_accepts_utf8_bom(self) -> None:
        source = Path("data/sample_issue.json").read_bytes()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "issue.json"
            path.write_bytes(b"\xef\xbb\xbf" + source)

            issue = load_issue(path)

        self.assertEqual(issue.issue, "sample-001")
        self.assertEqual(len(issue.matches), 14)


if __name__ == "__main__":
    unittest.main()
