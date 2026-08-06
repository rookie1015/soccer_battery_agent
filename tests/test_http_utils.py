import http.client
import unittest
import urllib.error
from unittest.mock import patch

from football_lottery_agent.http_utils import read_url_text


class _Response:
    def __init__(self, value: bytes | BaseException):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self) -> bytes:
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class HttpUtilsTests(unittest.TestCase):
    def test_retries_incomplete_response_and_discards_partial_body(self) -> None:
        truncated = http.client.IncompleteRead(b'{"partial":', 9)
        with patch(
            "football_lottery_agent.http_utils.urllib.request.urlopen",
            side_effect=[_Response(truncated), _Response(b'{"complete": true}')],
        ) as urlopen:
            text = read_url_text("https://example.test/data", timeout=1)

        self.assertEqual(text, '{"complete": true}')
        self.assertEqual(urlopen.call_count, 2)

    def test_exhausted_incomplete_responses_become_url_error(self) -> None:
        with patch(
            "football_lottery_agent.http_utils.urllib.request.urlopen",
            return_value=_Response(http.client.IncompleteRead(b"partial", 10)),
        ) as urlopen:
            with self.assertRaises(urllib.error.URLError):
                read_url_text("https://example.test/data", timeout=1, attempts=3)

        self.assertEqual(urlopen.call_count, 3)

    def test_http_status_error_is_not_retried(self) -> None:
        error = urllib.error.HTTPError("https://example.test", 404, "Not Found", None, None)
        with patch("football_lottery_agent.http_utils.urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(urllib.error.HTTPError):
                read_url_text("https://example.test/data", timeout=1)

        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
