"""
engine_base — Shared base class for all search engine scrapers.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from pipeline.http_client import HttpClient, Response

logger = logging.getLogger('lead_engine.engine')


class SearchResult:
    """One scraped search result item."""
    __slots__ = ('url', 'title', 'snippet', 'domain')

    def __init__(self, url: str, title: str, snippet: str) -> None:
        self.url     = url
        self.title   = title
        self.snippet = snippet
        self.domain  = _extract_base_domain(url)

    def __repr__(self) -> str:
        return f"<SearchResult domain={self.domain!r} title={self.title[:40]!r}>"


class BaseEngine(ABC):
    """
    Abstract base class for all search engine scrapers.

    Concrete subclasses must implement:
      - name          (class attribute) — engine label, e.g. 'bing'
      - _first_page() — returns {'url': str, 'data': dict|None}
      - _next_page(soup) — same shape, or url=None if no more pages
      - _parse_results(soup) — returns list[SearchResult]
    """

    name: str = 'base'

    def __init__(self, client: HttpClient,
                 delay_pages: tuple[float, float] = (8, 15)) -> None:
        self._client       = client
        self._delay_pages  = delay_pages
        self._query        = ''
        self._consecutive_429s = 0
        # Stored before _parse_results() is called so subclasses (e.g. DDG)
        # can inspect the HTTP status inside their own parser.
        self._last_status: int = 200
        self.is_banned = False

    @abstractmethod
    def _first_page(self) -> dict:
        """Return {'url': str, 'data': dict|None}."""

    @abstractmethod
    def _next_page(self, soup: BeautifulSoup) -> dict:
        """Return {'url': str|None, 'data': dict|None}."""

    @abstractmethod
    def _parse_results(self, soup: BeautifulSoup) -> list[SearchResult]:
        """Parse the BeautifulSoup tree; return list of SearchResult."""

    def search(self, query: str, pages: int = 5) -> list[SearchResult]:
        """
        Run `query` across up to `pages` pages.
        Returns a flat list of SearchResult objects.
        """
        self._query = query
        self._consecutive_429s = 0
        self.is_banned = False
        all_results: list[SearchResult] = []
        seen_domains: set[str] = set()

        self._client.rotate_ua()
        request = self._first_page()

        for page_num in range(1, pages + 1):
            url  = request.get('url')
            data = request.get('data')
            if not url:
                break

            response = self._fetch(url, data)

            if response.http == 429:
                self._consecutive_429s += 1
                if self._consecutive_429s >= 3:
                    logger.warning("[%s] 3 consecutive 429s — marking as banned", self.name)
                    self.is_banned = True
                    break
                wait = 600
                logger.warning("[%s] 429 — sleeping %ds", self.name, wait)
                time.sleep(wait)
                self._client.rotate_ua()
                continue
            else:
                self._consecutive_429s = 0

            # Store status before calling parse so subclasses can inspect it.
            # HTTP 202 from DDG Lite is a transient bot challenge (not a permanent
            # block) — allow it to fall through to _parse_results() for logging.
            self._last_status = response.http

            if response.http not in (200, 202):
                if response.http == 500:
                    logger.warning("[%s] HTTP 500 — rate-limited or server error, "
                                   "stopping query", self.name)
                else:
                    logger.warning("[%s] HTTP %d — stopping query",
                                   self.name, response.http)
                break

            soup    = BeautifulSoup(response.html, 'html.parser')
            results = self._parse_results(soup)

            new_results = []
            for r in results:
                if r.domain and r.domain not in seen_domains:
                    seen_domains.add(r.domain)
                    new_results.append(r)

            all_results.extend(new_results)
            logger.info("[%s] page=%d query=%r new=%d total=%d",
                        self.name, page_num, query[:40],
                        len(new_results), len(all_results))

            if self.is_banned:
                logger.warning("[%s] Engine flagged banned — stopping", self.name)
                break

            request = self._next_page(soup)
            if not request.get('url'):
                logger.debug("[%s] No next page found — done", self.name)
                break

            if page_num < pages:
                wait = random.uniform(*self._delay_pages)
                logger.debug("[%s] Page delay %.1fs", self.name, wait)
                time.sleep(wait)

        return all_results

    def _fetch(self, url: str, data: dict | None = None) -> Response:
        if data:
            return self._client.post(url, data)
        return self._client.get(url)

    @staticmethod
    def _text(tag) -> str:
        return tag.get_text(separator=' ', strip=True) if tag else ''

    @staticmethod
    def _attr(tag, attr: str) -> str:
        return (tag.get(attr) or '') if tag else ''


def _extract_base_domain(url: str) -> str:
    """
    Return the registrable domain (no www, no path, lowercase).
    e.g. 'https://www.abc-lettings.co.uk/contact' → 'abc-lettings.co.uk'
    """
    try:
        parsed = urlparse(url)
        host   = parsed.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]
        return host.split(':')[0]
    except Exception:
        return ''
