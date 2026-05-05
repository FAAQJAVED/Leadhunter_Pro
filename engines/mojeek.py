"""
engines.mojeek — Mojeek search engine scraper.

URL pattern:
  https://www.mojeek.com/search?q={query}&fmt=html&lang=en&hp=0&arc=none

Confirmed working selectors:
  a.ob          → 10 result URL links
  h2 a[href]    → 10 result titles (fallback)
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from engine_base import BaseEngine, SearchResult, _extract_base_domain

logger = logging.getLogger('lead_engine.mojeek')
_BASE = 'https://www.mojeek.com'


class MojeekEngine(BaseEngine):
    name = 'mojeek'

    def _first_page(self) -> dict:
        encoded = quote_plus(self._query)
        url = f'{_BASE}/search?q={encoded}&fmt=html&lang=en&hp=0&arc=none'
        return {'url': url, 'data': None}

    def _next_page(self, soup: BeautifulSoup) -> dict:
        next_tag = (soup.select_one('a.next[href]')
                    or soup.select_one('a[rel="next"][href]'))
        if not next_tag:
            for a in soup.select('div.pagination a[href], nav a[href]'):
                txt = a.get_text(strip=True).lower()
                if txt in ('next', '›', '>>', 'next »', '>'):
                    next_tag = a
                    break
        if not next_tag:
            return {'url': None, 'data': None}
        href = next_tag.get('href', '')
        url  = (_BASE + href) if href.startswith('/') else href
        return {'url': url, 'data': None}

    def _parse_results(self, soup: BeautifulSoup) -> list[SearchResult]:
        page_text = soup.get_text(strip=True)
        if len(page_text) < 300:
            logger.warning('[mojeek] Page too short — error response')
            return []

        results: list[SearchResult] = []
        # Per-page domain dedup: Mojeek can return two paths of the same
        # domain in one page (e.g. example.com/london + example.com/city).
        # Deduping here prevents wasting result slots.
        seen_domains: set[str] = set()

        # PRIMARY: Use a.ob — confirmed working (10 matches in diagnostic)
        ob_links = soup.select('a.ob[href]')

        if ob_links:
            logger.debug('[mojeek] a.ob selector matched %d links', len(ob_links))
            for a in ob_links:
                url = a.get('href', '')
                if not url.startswith('http') or 'mojeek.com' in url:
                    continue

                domain = _extract_base_domain(url)
                if domain and domain in seen_domains:
                    continue
                if domain:
                    seen_domains.add(domain)

                container = a.find_parent('li') or a.find_parent('div')
                title_tag = None
                if container:
                    title_tag = (container.select_one('h2')
                                 or container.select_one('h3')
                                 or container.select_one('a.title'))
                title = self._text(title_tag) if title_tag else self._text(a)

                snippet_tag = None
                if container:
                    snippet_tag = (container.select_one('p.s')
                                   or container.select_one('p.result-desc')
                                   or container.select_one('p'))
                snippet = self._text(snippet_tag)

                results.append(SearchResult(url=url, title=title, snippet=snippet))

        if results:
            return results

        # FALLBACK: h2 > a pattern (also confirmed: 10 matches)
        logger.debug('[mojeek] a.ob matched nothing — trying h2 a[href] fallback')
        for h2 in soup.select('h2'):
            a = h2.find('a', href=True)
            if not a:
                continue
            url = a.get('href', '')
            if not url.startswith('http') or 'mojeek.com' in url:
                continue

            domain = _extract_base_domain(url)
            if domain and domain in seen_domains:
                continue
            if domain:
                seen_domains.add(domain)

            title     = self._text(h2)
            container = h2.find_parent('li') or h2.find_parent('div')
            snippet_tag = container.select_one('p') if container else None
            snippet   = self._text(snippet_tag)
            results.append(SearchResult(url=url, title=title, snippet=snippet))

        return results
