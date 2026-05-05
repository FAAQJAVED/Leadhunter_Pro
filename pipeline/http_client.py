"""
pipeline.http_client — httpx Client with exponential backoff and UA rotation.
"""

from __future__ import annotations

import random
import time
import logging
from collections import namedtuple
from urllib.parse import quote, unquote

import httpx

from config import (
    CONNECT_TIMEOUT, READ_TIMEOUT, FOLLOW_REDIRECTS,
    HTTP2_ENABLED, MAX_RETRIES, USER_AGENTS,
)

logger = logging.getLogger('lead_engine.http')

# Simple container returned by every request
Response = namedtuple('Response', ['http', 'html'])

# Status codes that trigger a retry with exponential backoff
_RETRY_STATUSES = {429, 502, 503, 504}


class HttpClient:
    """
    httpx-based HTTP client with:
      - Separate connect / read timeouts
      - Rotating User-Agent (never the same UA twice in a row)
      - Exponential backoff retry (up to MAX_RETRIES attempts)
      - Returns Response(http, html) namedtuple
    """

    def __init__(self, proxy: str | None = None) -> None:
        self._ua_pool = USER_AGENTS.copy()
        self._last_ua: str = ''
        self._proxy = proxy

        timeout = httpx.Timeout(10.0, connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                                write=10.0, pool=5.0)

        client_kwargs: dict = dict(
            timeout=timeout,
            follow_redirects=FOLLOW_REDIRECTS,
            headers=self._build_base_headers(),
        )
        if proxy:
            client_kwargs['proxies'] = {'http://': proxy, 'https://': proxy}

        # http2=True needs the optional httpx[http2] extra (h2 package).
        # Fall back to HTTP/1.1 gracefully if not installed.
        if HTTP2_ENABLED:
            try:
                import h2  # noqa: F401
                client_kwargs['http2'] = True
            except ImportError:
                logger.warning("h2 not installed — HTTP/2 disabled. "
                               "Run: pip install httpx[http2]")

        self.session = httpx.Client(**client_kwargs)

    def get(self, url: str) -> Response:
        """GET with retry/backoff. Returns Response(http, html)."""
        url = self._encode_url(url)
        return self._request('GET', url)

    def post(self, url: str, data: dict) -> Response:
        """POST with retry/backoff. Returns Response(http, html)."""
        url = self._encode_url(url)
        return self._request('POST', url, data=data)

    def rotate_ua(self) -> str:
        """Pick a new UA that is different from the last one."""
        pool = [ua for ua in self._ua_pool if ua != self._last_ua]
        if not pool:
            pool = self._ua_pool
        ua = random.choice(pool)
        self._last_ua = ua
        self.session.headers.update({'User-Agent': ua})
        logger.debug("UA rotated → %s", ua[:60])
        return ua

    def set_headers(self, headers: dict) -> None:
        """Merge additional headers into the session."""
        self.session.headers.update(headers)

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, url: str,
                 data: dict | None = None) -> Response:
        last_exc: Exception | None = None
        last_status: int = 0

        for attempt in range(MAX_RETRIES + 1):
            try:
                if method == 'GET':
                    resp = self.session.get(url)
                else:
                    resp = self.session.post(url, data=data)

                self.session.headers.update({'Referer': url})

                if resp.status_code in _RETRY_STATUSES:
                    last_status = resp.status_code
                    wait = self._backoff(attempt)
                    logger.warning("HTTP %d on attempt %d/%d — waiting %.1fs",
                                   resp.status_code, attempt + 1,
                                   MAX_RETRIES + 1, wait)
                    time.sleep(wait)
                    self.rotate_ua()
                    continue

                return Response(http=resp.status_code, html=resp.text)

            except (httpx.ConnectError, httpx.TimeoutException,
                    httpx.RemoteProtocolError) as exc:
                last_exc = exc
                wait = self._backoff(attempt)
                logger.warning("Network error on attempt %d/%d (%s) — "
                               "waiting %.1fs", attempt + 1,
                               MAX_RETRIES + 1, type(exc).__name__, wait)
                time.sleep(wait)
                self.rotate_ua()

        msg = str(last_exc) if last_exc else f"HTTP {last_status}"
        logger.error("Request failed after %d attempts: %s", MAX_RETRIES + 1, msg)
        return Response(http=last_status or 0, html=msg)

    @staticmethod
    def _backoff(attempt: int) -> float:
        """2^attempt + random jitter in [0, 1)."""
        return (2 ** attempt) + random.random()

    @staticmethod
    def _build_base_headers() -> dict:
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
        }

    @staticmethod
    def _encode_url(url: str) -> str:
        """Only percent-encode if the URL isn't already encoded."""
        decoded = unquote(url)
        if decoded == url:
            url = quote(url, safe=':/?=&#+%@,;')
        return url
