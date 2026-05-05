"""
engines.yahoo — Yahoo Search HTML scraper.

URL pattern:
  https://search.yahoo.com/search?p={query}&b=1&pz=10&vl=lang_en

Current HTML structure (confirmed):
  Pattern A organic:   div.compTitle > a[href*="/RU="]       (direct child)
  Pattern B organic:   div.compTitle > h3 > a[href*="/RU="]  (wrapped in h3)
  Sitelinks:           li.mt-6  (skip entirely)
  Snippet:             div.compText  or  p

Yahoo uses TWO compTitle anchor patterns in the wild:
  Pattern A (approx 7 results): div.compTitle > a[href*="/RU="]
  Pattern B (approx 3 results): div.compTitle > h3 > a[href*="/RU="]
The combined CSS selector in _parse_primary() covers both → 10/10 results.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, unquote, urlparse

from bs4 import BeautifulSoup

from engine_base import BaseEngine, SearchResult

logger = logging.getLogger('lead_engine.yahoo')

_BASE = 'https://search.yahoo.com'


def _extract_yahoo_url(href: str) -> str:
    """
    Yahoo wraps every result URL in a redirect like:
      https://r.search.yahoo.com/...RU=https%3A%2F%2Factual.com%2F/RK=2/RS=...
    The real URL lives in the /RU= path segment.
    """
    if not href:
        return ''
    if '/RU=' in href:
        try:
            ru_segment = href.split('/RU=')[1].split('/')[0]
            real = unquote(ru_segment)
            if real.startswith('http') and 'yahoo.com' not in real:
                return real
        except Exception:
            pass
    if href.startswith('http') and 'yahoo.com' not in href:
        return href
    return ''


def _root_domain(url: str) -> str:
    """Return root domain for sitelink dedup."""
    try:
        return urlparse(url).netloc.lower().lstrip('www.')
    except Exception:
        return url


def _clean_yahoo_title(raw: str) -> str:
    """
    CHANGE 2: Strip URL bleeding and breadcrumb separators from Yahoo titles.

    Yahoo's title node can contain the URL bleeding in:
      "Philip James https://www.philipjames.co.uk › property"
    → "Philip James"
    """
    title = re.sub(r'https?://\S.*$', '', raw).strip()
    title = re.sub(r'\s{2,}', ' ', title).strip()
    title = re.split(r'\s+[›»]\s+', title)[0].strip()
    return title


class YahooEngine(BaseEngine):
    """Yahoo Search HTML scraper. Paginates via b= offset (1-based, step 10)."""

    name = 'yahoo'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._offset = 1

    def _first_page(self) -> dict:
        self._offset = 1
        self._client.set_headers({'Referer': 'https://search.yahoo.com/'})
        return self._build_request()

    def _next_page(self, soup: BeautifulSoup) -> dict:
        next_tag = (
            soup.select_one('a#pg-next')
            or soup.select_one('a[aria-label="Next"]')
            or soup.select_one('a.next')
        )
        if next_tag:
            href = next_tag.get('href', '')
            if href:
                url = (_BASE + href) if href.startswith('/') else href
                if 'b=' in url:
                    try:
                        self._offset = int(url.split('b=')[1].split('&')[0])
                    except Exception:
                        self._offset += 10
                return {'url': url, 'data': None}

        self._offset += 10
        if self._offset > 91:
            return {'url': None, 'data': None}
        return self._build_request()

    def _build_request(self) -> dict:
        encoded = quote_plus(self._query)
        url = (
            f'{_BASE}/search'
            f'?p={encoded}'
            f'&b={self._offset}'
            f'&pz=10'
            f'&vl=lang_en'
            f'&fl=1'
        )
        return {'url': url, 'data': None}

    def _parse_results(self, soup: BeautifulSoup) -> list[SearchResult]:
        page_text = soup.get_text(strip=True)
        if len(page_text) < 300:
            logger.warning('[yahoo] Page too short — possible bot block')
            return []
        if 'captcha' in page_text.lower():
            logger.warning('[yahoo] CAPTCHA detected')
            self.is_banned = True
            return []

        results = self._parse_primary(soup)
        if not results:
            results = self._parse_fallback(soup)

        if not results:
            logger.warning('[yahoo] No results — selector may have changed')
        else:
            logger.debug('[yahoo] Parsed %d results (after sitelink dedup)', len(results))

        return results

    def _parse_primary(self, soup: BeautifulSoup) -> list[SearchResult]:
        """
        Yahoo uses TWO compTitle anchor patterns in live HTML:
          Pattern A: div.compTitle > a[href*="/RU="]       (direct child)
          Pattern B: div.compTitle > h3 > a[href*="/RU="]  (wrapped in h3)

        Combined CSS selector picks up both patterns.
        Per-domain dedup is applied to prevent sitelink contamination.
        """
        results: list[SearchResult] = []
        seen_domains: set[str] = set()

        title_anchors = soup.select(
            'div.compTitle > a[href], '
            'div.compTitle > h3 > a[href]'
        )

        # Last-resort fallback: h3 > a with /RU= (no compTitle dependency)
        if not title_anchors:
            title_anchors = [
                a for a in soup.select('h3 a[href]')
                if '/RU=' in a.get('href', '')
            ]

        for a in title_anchors:
            raw_href = a.get('href', '')
            if '/RU=' not in raw_href:
                continue

            url = _extract_yahoo_url(raw_href)
            if not url or not url.startswith('http') or 'yahoo.com' in url:
                continue

            root = _root_domain(url)
            if root in seen_domains:
                logger.debug('[yahoo] Sitelink dropped (domain seen): %s', url)
                continue
            seen_domains.add(root)

            # Prefer the h3 parent text, fall back to the anchor itself
            title_node = a.find_parent('h3') or a
            raw_title  = self._text(title_node)
            # CHANGE 2: strip URL bleeding and breadcrumb separators
            title = _clean_yahoo_title(raw_title)

            snippet_tag = None
            parent_block = a.find_parent('li') or a.find_parent('div')
            if parent_block:
                snippet_tag = (
                    parent_block.select_one('div.compText')
                    or parent_block.select_one('p.lh-16')
                    or parent_block.select_one('span.fc-2nd')
                    or parent_block.select_one('p')
                )

            results.append(SearchResult(
                url=url,
                title=title,
                snippet=self._text(snippet_tag),
            ))

        return results

    def _parse_fallback(self, soup: BeautifulSoup) -> list[SearchResult]:
        """
        Fallback: scan all a[href] containing /RU= — handles Yahoo HTML changes.
        Per-domain dedup prevents sitelink contamination.
        First URL per root domain is kept (homepage wins over subpages).
        """
        logger.debug('[yahoo] Using /RU= href fallback')
        seen_urls:    set[str] = set()
        seen_domains: set[str] = set()
        results: list[SearchResult] = []

        for a in soup.select('a[href]'):
            raw_href = a.get('href', '')
            if '/RU=' not in raw_href:
                continue

            url = _extract_yahoo_url(raw_href)
            if not url or url in seen_urls:
                continue

            root = _root_domain(url)
            if root in seen_domains:
                logger.debug('[yahoo] Fallback sitelink dropped: %s', url)
                continue

            seen_urls.add(url)
            seen_domains.add(root)

            container  = (a.find_parent('li') or a.find_parent('div') or
                          a.find_parent('article'))
            title_tag   = container.select_one('h3') if container else None
            snippet_tag = container.select_one('p')  if container else None

            raw_title = self._text(title_tag) if title_tag else self._text(a)
            # CHANGE 2: strip URL bleeding and breadcrumb separators
            title = _clean_yahoo_title(raw_title)

            results.append(SearchResult(
                url=url,
                title=title,
                snippet=self._text(snippet_tag),
            ))

        return results
