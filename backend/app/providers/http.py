"""Shared async HTTP client.

One pooled ``httpx.AsyncClient`` for the whole process.  This is not a detail:
on a high-latency coastal link, a fresh TLS handshake per provider costs more
than the request itself, and four providers each opening their own connection
is most of the difference between a 4-second answer and a sub-second one.
"""

from __future__ import annotations

import httpx

from app.config.settings import get_settings

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        s = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=s.provider_connect_timeout_ms / 1000.0,
                read=60.0,
                write=s.provider_connect_timeout_ms / 1000.0,
                pool=s.provider_connect_timeout_ms / 1000.0,
            ),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16,
                                keepalive_expiry=60.0),
            headers={"User-Agent": f"ORCA/{s.version} (SIH26176 marine decision support)",
                     "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
            http2=False,
            verify=False,
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
