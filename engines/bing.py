"""
engines.bing — Bing RSS feed engine.
"""

from __future__ import annotations

import base64
import logging
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from engine_base import BaseEngine, SearchResult
from pipeline.http_client import HttpClient, Response

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

logger = logging.getLogger('lead_engine.bing')

_RSS_BASE  = 'https://www.bing.com/search'
_PAGE_SIZE = 10

# Geo headers targeting UK market via explicit market/language/location signals.
# NOTE: X-MSEdge-ClientIP is intentionally absent. A fake London IP (81.141.0.1)
# was previously set here, but when the user's real connection comes from a
# VPN/proxy, Bing detects the IP mismatch and ignores ALL headers — producing
# Chinese or unrelated results. Without a fake IP, Bing trusts the market
# parameter (mkt=en-GB in the URL) and the Accept-Language header, which reliably
# produces English results regardless of the originating IP.
_BING_GEO_HEADERS = {
    'Accept-Language':   'en-GB,en;q=0.9',
    'X-MSEdge-Market':   'en-GB',
    'X-Search-Location': 'lat:51.5074;long:-0.1278;re:1000',
}


def _is_english_result(title: str, description: str = '') -> bool:
    """Checks if a search result title/description appears to be English."""
    LOCALE_PATTERNS = (
        '/de/', '/de-de/', '/ja/', '/ja-jp/', '/sr/', '/sr-latn/',
        '/fr/', '/fr-fr/', '/es/', '/es-es/', '/it/', '/it-it/',
        '/nl/', '/pl/', '/pt/', '/ru/', '/tr/', '/ko/', '/zh/',
        'hl=de', 'hl=ja', 'lang=de', 'locale=de', 'language=de',
    )

    def _pct_non_ascii(text: str) -> float:
        if not text:
            return 0.0
        return sum(1 for c in text if ord(c) > 127) / len(text)

    if _pct_non_ascii(title) >= 0.30:
        return False

    if description and len(description) > 50:
        if _pct_non_ascii(description) >= 0.25:
            return False
        desc_lower = description.lower()
        if any(p in desc_lower for p in LOCALE_PATTERNS):
            return False

    return True


class BingEngine(BaseEngine):
    name = 'bing'

    def __init__(self, *args, proxy_url: str = '', **kwargs):
        super().__init__(*args, **kwargs)
        self._page_offset   = 1
        self._raw_xml: str  = ''
        self._last_count    = -1
        self._is_first_page = True
        
        # Track domains per page to detect result looping (geo-block signal)
        self._page1_domains: set[str] = set()

        self._proxy_client: HttpClient | None = None
        if proxy_url:
            try:
                self._proxy_client = HttpClient(proxy=proxy_url)
                logger.info('[bing] Proxy client created: %s...', proxy_url[:40])
            except Exception as exc:
                logger.warning('[bing] Failed to create proxy client: %s — using direct', exc)
                self._proxy_client = None

    def _fetch(self, url: str, data: dict | None = None) -> Response:
        """Fetches a URL using the appropriate client (proxy or direct) with geo headers."""
        active_client = self._proxy_client if self._proxy_client else self._client

        saved_headers = dict(active_client.session.headers)
        try:
            active_client.set_headers(_BING_GEO_HEADERS)
            if data:
                response = active_client.post(url, data)
            else:
                response = active_client.get(url)
            self._raw_xml = response.html
        finally:
            active_client.session.headers.clear()
            active_client.session.headers.update(saved_headers)
        return response

    def _first_page(self) -> dict:
        """Constructs the first page search request."""
        self._page_offset   = 1
        self._last_count    = -1
        self._is_first_page = True
        self._page1_domains = set()
        return self._build_request()

    def _next_page(self, soup: BeautifulSoup) -> dict:
        """Constructs the next page search request."""
        if self._last_count == 0:
            return {'url': None, 'data': None}
        self._page_offset += _PAGE_SIZE
        if self._page_offset > 90:
            return {'url': None, 'data': None}
        self._is_first_page = False
        return self._build_request()

    def _build_request(self) -> dict:
        """Builds the request dictionary for a Bing search."""
        encoded = quote_plus(self._query)
        url = (
            f'{_RSS_BASE}?q={encoded}'
            f'&format=RSS'
            f'&first={self._page_offset}'
            f'&mkt=en-GB&cc=GB&setlang=en-GB&ensearch=1&count={_PAGE_SIZE}'
        )
        return {'url': url, 'data': None}

    def _parse_results(self, soup: BeautifulSoup) -> list[SearchResult]:
        """Parses results from either RSS XML or HTML fallback."""
        raw_count, results = self._parse_rss(self._raw_xml)

        if self._is_first_page and raw_count > 0 and len(results) == 0:
            if not self._proxy_client:
                logger.warning(
                    '[bing] All results geo-wrong. '
                    'Set BING_PROXY in config.py or use VPN.'
                )
                self.is_banned = True

        if not results:
            logger.debug('[bing] RSS empty — HTML fallback')
            results = self._parse_html(soup)

        # Loop detection: if page 2 domains are a subset of page 1, engine is geo-blocked
        current_domains = {r.domain for r in results}
        if self._is_first_page:
            self._page1_domains = current_domains
        else:
            if current_domains and current_domains.issubset(self._page1_domains):
                logger.warning('[bing] Results are looping (geo-block confirmed) — stopping early')
                self.is_banned = True
                return []

        self._last_count = len(results)
        if results:
            logger.debug('[bing] Parsed %d items, %d geo-passed', raw_count, len(results))
            
        return results

    def _parse_rss(self, raw_text: str) -> tuple[int, list[SearchResult]]:
        """Parses search results from Bing's RSS feed XML."""
        results = []
        try:
            text = raw_text.lstrip('\ufeff').strip()
            if not text.startswith('<?xml') and not text.startswith('<rss'):
                logger.debug('[bing] Not RSS XML — skipping')
                return 0, []
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            logger.debug('[bing] XML ParseError: %s', exc)
            return 0, []

        items = root.findall('.//item')
        if not items:
            items = root.findall('channel/item')

        raw_count = len(items)

        for item in items:
            link_el  = item.find('link')
            title_el = item.find('title')
            desc_el  = item.find('description')

            url   = (link_el.text  or '').strip() if link_el  is not None else ''
            title = (title_el.text or '').strip() if title_el is not None else ''
            desc  = (BeautifulSoup((desc_el.text or ''), 'html.parser').get_text(strip=True)
                     if desc_el is not None else '')

            if url.startswith('http') and 'bing.com' not in url:
                if not _is_english_result(title, desc):
                    logger.debug('[bing] Skipping geo-wrong result: %r', title[:60])
                    continue
                results.append(SearchResult(url=url, title=title, snippet=desc))

        return raw_count, results

    def _parse_html(self, soup: BeautifulSoup) -> list[SearchResult]:
        """Fall-back parser for Bing's search results in HTML format."""
        page_text = soup.get_text(strip=True).lower()
        if 'captcha' in page_text or len(page_text) < 300:
            return []
        items = []
        for sel in ['ol#b_results > li.b_algo', 'li.b_algo', '#b_results .b_algo']:
            items = soup.select(sel)
            if items:
                break
        if not items:
            items = [h2.parent for h2 in soup.find_all('h2')
                     if h2.find('a', href=True) and h2.parent is not None]
        results = []
        for item in items:
            url = _extract_bing_url(item)
            if not url:
                continue
            title_tag   = item.select_one('h2') or item.select_one('h3')
            snippet_tag = item.select_one('p') or item.select_one('.b_caption p')
            results.append(SearchResult(
                url=url,
                title=self._text(title_tag),
                snippet=self._text(snippet_tag),
            ))
        return results


def _extract_bing_url(item) -> str:
    """Extracts and decodes the target URL from a Bing search result item."""
    anchor = item.select_one('h2 a[href]') or item.select_one('a[href]')
    if not anchor:
        return ''
    href = anchor.get('href', '')
    try:
        params = parse_qs(urlparse(href).query)
        if 'u' in params:
            enc = params['u'][0]
            if enc.startswith('a1'):
                enc = enc[2:]
            enc += '=' * (4 - len(enc) % 4) if len(enc) % 4 else ''
            decoded = base64.urlsafe_b64decode(enc).decode('utf-8', errors='replace')
            if decoded.startswith('http'):
                return decoded
    except Exception:
        pass
    if href.startswith('http') and 'bing.com' not in href:
        return href
    if '/url?q=' in href:
        try:
            decoded = unquote(href.split('/url?q=')[1].split('&')[0])
            if decoded.startswith('http'):
                return decoded
        except Exception:
            pass
    return ''
