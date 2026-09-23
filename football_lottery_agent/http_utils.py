from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any


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
    Network failures, truncated responses and transient HTTP statuses are
    retried with backoff. Permanent 4xx responses fail immediately.
    """
    text, _ = read_url_text_with_headers(
        request,
        timeout=timeout,
        attempts=attempts,
        encoding=encoding,
        cancel_check=cancel_check,
    )
    return text


def read_url_text_with_headers(
    request: str | urllib.request.Request,
    *,
    timeout: float,
    attempts: int = 3,
    encoding: str = "utf-8",
    cancel_check: Callable[[], None] | None = None,
) -> tuple[str, Any]:
    """Read a complete response while preserving its response headers."""
    attempts = max(1, int(attempts))
    last_error: BaseException | None = None
    for attempt in range(attempts):
        if cancel_check is not None:
            cancel_check()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode(encoding, errors="replace")
                if cancel_check is not None:
                    cancel_check()
                return text, getattr(response, "headers", {})
        except urllib.error.HTTPError as exc:
            last_error = exc
            if not _retryable_http_status(exc.code) or attempt + 1 >= attempts:
                raise
            _wait_before_retry(attempt, exc.headers, cancel_check)
        except (http.client.HTTPException, urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                _wait_before_retry(attempt, None, cancel_check)
    if isinstance(last_error, urllib.error.HTTPError):
        raise last_error
    raise urllib.error.URLError(last_error or "HTTP response could not be read completely")


def _retryable_http_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599


def _wait_before_retry(
    attempt: int,
    headers: Any,
    cancel_check: Callable[[], None] | None,
) -> None:
    delay = _retry_after_seconds(headers)
    if delay is None:
        delay = min(4.0, 0.5 * (2**attempt))
    else:
        delay = min(30.0, delay)
    deadline = time.monotonic() + max(0.0, delay)
    while True:
        if cancel_check is not None:
            cancel_check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _retry_after_seconds(headers: Any) -> float | None:
    if headers is None:
        return None
    try:
        value = str(headers.get("Retry-After") or "").strip()
    except (AttributeError, TypeError):
        return None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return max(0.0, retry_at.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None
