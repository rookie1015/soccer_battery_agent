from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .json_utils import loads_json


DBPEDIA_SPARQL_URL = "https://dbpedia.org/sparql"
DBPEDIA_CACHE_SECONDS = 86400 * 30


def fetch_dbpedia_club_aliases(local_name: str, cache_dir: str | Path) -> tuple[str, ...]:
    """Resolve a Chinese club abbreviation to English labels without guessing.

    DBpedia is used only as a bilingual bridge. The returned labels must still
    match both sides of a provider fixture in the caller before any identity is
    persisted.
    """
    clean_name = local_name.strip()
    if not clean_name or not re.search(r"[\u4e00-\u9fff]", clean_name):
        return ()
    escaped_name = clean_name.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        "SELECT DISTINCT ?s ?zh ?en WHERE { "
        "?s a <http://dbpedia.org/ontology/SoccerClub> ; "
        "<http://www.w3.org/2000/01/rdf-schema#label> ?zh . "
        f"FILTER(lang(?zh)='zh' && CONTAINS(STR(?zh), '{escaped_name}')) "
        "OPTIONAL { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?en . "
        "FILTER(lang(?en)='en') } } LIMIT 8"
    )
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    url = f"{DBPEDIA_SPARQL_URL}?{params}"
    payload = _fetch_json(url, Path(cache_dir) / "team_identity_lookup")
    bindings = (((payload or {}).get("results") or {}).get("bindings") or []) if isinstance(payload, dict) else []
    aliases: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        english = str(((binding.get("en") or {}).get("value") or "")).strip()
        if not english:
            continue
        for alias in _club_alias_variants(english):
            if alias and alias.casefold() not in {item.casefold() for item in aliases}:
                aliases.append(alias)
    return tuple(aliases)


def _club_alias_variants(label: str) -> tuple[str, ...]:
    clean = re.sub(r"\s+", " ", label).strip()
    without_suffix = re.sub(
        r"(?:\s+(?:A\.?F\.?C\.?|F\.?C\.?|S\.?C\.?|Football Club|Association Football Club))+$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip(" .")
    return tuple(dict.fromkeys(item for item in (clean, without_suffix) if item))


def _fetch_json(url: str, cache_dir: Path) -> Any:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    cached = _read_cache(cache_path)
    if cached is not None and datetime.now().timestamp() - cache_path.stat().st_mtime <= DBPEDIA_CACHE_SECONDS:
        return cached
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/sparql-results+json, application/json",
            "User-Agent": "football-lottery-agent/0.2",
        },
    )
    try:
        text = _download_text(url, request)
        payload = loads_json(text)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TypeError, ValueError):
        return cached
    cache_path.write_text(text, encoding="utf-8")
    return payload


def _download_text(url: str, request: urllib.request.Request) -> str:
    """Use Android's native TLS stack when running inside Chaquopy."""
    try:
        from java.io import BufferedReader, InputStreamReader  # type: ignore[import-not-found]
        from java.lang import StringBuilder  # type: ignore[import-not-found]
        from java.net import URL  # type: ignore[import-not-found]
    except ImportError:
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLError):
                raise
            return _download_resolved_https(url)

    connection = URL(url).openConnection()
    connection.setConnectTimeout(12000)
    connection.setReadTimeout(12000)
    connection.setRequestProperty("Accept", "application/sparql-results+json, application/json")
    connection.setRequestProperty("User-Agent", "football-lottery-agent/0.2")
    reader = BufferedReader(InputStreamReader(connection.getInputStream(), "UTF-8"))
    builder = StringBuilder()
    try:
        while True:
            line = reader.readLine()
            if line is None:
                break
            builder.append(line)
    finally:
        reader.close()
        connection.disconnect()
    return str(builder.toString())


def _download_resolved_https(url: str) -> str:
    """Retry a TLS endpoint through its resolved IPv4 while preserving SNI."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise urllib.error.URLError("Resolved HTTPS retry requires an HTTPS hostname")
    address = socket.gethostbyname(parsed.hostname)
    connection = _ResolvedHTTPSConnection(parsed.hostname, address, timeout=12)
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/sparql-results+json, application/json",
                "User-Agent": "football-lottery-agent/0.2",
                "Host": parsed.hostname,
            },
        )
        response = connection.getresponse()
        if response.status >= 400:
            raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
        return response.read().decode("utf-8", errors="replace")
    finally:
        connection.close()


class _ResolvedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, resolved_address: str, timeout: float):
        super().__init__(hostname, timeout=timeout, context=ssl.create_default_context())
        self._resolved_address = resolved_address

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._resolved_address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _read_cache(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return loads_json(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
