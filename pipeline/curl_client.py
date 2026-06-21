"""
pipeline.curl_client — curl_cffi-based HTTP client with TLS/Chrome impersonation.

Used exclusively by engines/yahoo.py. CONFIRMED via diagnose_curl_cffi.py
live experiment (2026-06-18):

    Engine | httpx (full header set, two-step warmup) | curl_cffi (cold, minimal headers)
    -------|--------------------------------------------|-----------------------------------
    Yahoo  | HTTP 500, 0 chars — every run               | HTTP 200, 9 compTitle results
    Mojeek | HTTP 200, 10/10 results                      | HTTP 200, 10/10 results (no change)
    Bing   | HTTP 200, working                            | HTTP 200, working (no change)
    DDG    | HTTP 200, working                             | HTTP 200, working (no change)

Only Yahoo benefits. Mojeek/Bing/DDG are untouched and continue using the
shared httpx-based HttpClient exactly as before — do not route them through
this client.

Why this exists instead of extending HttpClient
-------------------------------------------------
httpx/requests use Python's stdlib `ssl` module, which produces a TLS
ClientHello fingerprint (JA3) identifiable as non-browser traffic regardless
of HTTP header sophistication. curl_cffi wraps libcurl + BoringSSL to
replicate a genuine Chrome TLS handshake (cipher suite order, extensions,
ALPN). This is a transport-layer property — no amount of header tuning on
httpx can replicate it. Hence a separate client class, not a header tweak.

No warmup required
-------------------
The old httpx-based Yahoo warmup (two-step yahoo.com → search.yahoo.com,
500-retry-with-cooldown logic) is now dead weight. The live experiment
succeeded on a single cold GET with only Accept + Accept-Language headers —
no cookies, no Referer, no prior request. engines/yahoo.py no longer warms
up or sets Referer; main.py's _do_engine_warmup() skips Yahoo entirely.
"""

from __future__ import annotations

import logging
import random

from curl_cffi.requests import Session as CurlSession

from pipeline.http_client import Response

logger = logging.getLogger('lead_engine.curl_client')

# Same rotation pool validated in the diagnose_curl_cffi.py experiment —
# all confirmed to produce a HTTP 200 against Yahoo in live testing.
_IMPERSONATE_POOL = [
    "chrome120", "chrome123", "chrome124", "chrome131", "chrome133a",
]

# Minimal headers — confirmed sufficient in the live experiment. Deliberately
# NOT adding Sec-Fetch-*/Sec-CH-UA/Cache-Control: the TLS impersonation is
# what's doing the work, and the tested-working config used only these two.
_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class CurlCffiClient:
    """
    Lightweight curl_cffi-backed client matching HttpClient's public
    interface (get/post → Response(http, html)) so BaseEngine._fetch()
    overrides can swap transports without changing the engine search() loop.
    """

    def __init__(self) -> None:
        self._last_impersonate: str = ''

    def get(self, url: str) -> Response:
        return self._request('GET', url)

    def post(self, url: str, data: dict) -> Response:
        return self._request('POST', url, data=data)

    def close(self) -> None:
        pass  # curl_cffi Session is created/closed per-request; nothing to release.

    def _request(self, method: str, url: str, data: dict | None = None) -> Response:
        impersonate = self._rotate_impersonate()
        try:
            with CurlSession() as session:
                if method == 'GET':
                    resp = session.get(url, headers=_HEADERS,
                                       impersonate=impersonate, timeout=15.0)
                else:
                    resp = session.post(url, data=data, headers=_HEADERS,
                                        impersonate=impersonate, timeout=15.0)
                logger.debug("[curl_cffi] %s %s -> HTTP %d (impersonate=%s)",
                            method, url[:70], resp.status_code, impersonate)
                return Response(http=resp.status_code, html=resp.text)
        except Exception as exc:
            logger.error("[curl_cffi] Request failed (impersonate=%s): %s", impersonate, exc)
            return Response(http=0, html=str(exc))

    def _rotate_impersonate(self) -> str:
        """Pick a Chrome version different from the last one used."""
        pool = [v for v in _IMPERSONATE_POOL if v != self._last_impersonate]
        if not pool:
            pool = _IMPERSONATE_POOL
        choice = random.choice(pool)
        self._last_impersonate = choice
        return choice