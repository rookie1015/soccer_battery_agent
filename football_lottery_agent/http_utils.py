from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable


def read_url_text(
    request: str | urllib.request.Request,
    *,
    timeout: float,
    attempts: int = 3,
    encoding: str = "utf-8",
    cancel_check: Callable[[], None] | None = None,
) -> str:
    """Read a complete HTTP response, retrying truncated mobile downloads.

    JSON and HTML responses must never be parsed or cached when the server
    closes the connection before the advertised Content-Length is received.
    HTTP status errors remain the caller's responsibility; connection-level
    failures are retried and normalized to URLError after the final attempt.
    """
    attempts = max(1, int(attempts))
    last_error: BaseException | None = None
    for _ in range(attempts):
        if cancel_check is not None:
            cancel_check()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode(encoding, errors="replace")
                if cancel_check is not None:
                    cancel_check()
                return text
        except urllib.error.HTTPError:
            raise
        except (http.client.HTTPException, urllib.error.URLError, OSError) as exc:
            last_error = exc
    raise urllib.error.URLError(last_error or "HTTP response could not be read completely")
