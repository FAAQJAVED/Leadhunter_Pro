"""
engines.duckduckgo — DuckDuckGo Lite engine.

Uses https://lite.duckduckgo.com/lite/ (POST endpoint).
Much lower CAPTCHA rate than html.duckduckgo.com.
No brotli needed — plain HTML, no compression.

Result structure (DDG Lite):
  <table>
    <tr class="result-link-row|...">
      <td ...><a class="result-link" href="https://real-url.com">Title</a></td>
    </tr>
    <tr class="result-snippet-row|...">
      <td class="result-snippet">Snippet text here.</td>
    </tr>
  </table>
  <form ...>
    <input name="q" value="...">
    <input name="s" value="25">   ← next offset
  </form>

Warmup note: DDG Lite returns HTTP 202 (bot challenge) when the session
has gone stale. The per-engine warmup in main.py runs immediately before
the first request (≤2 s gap) to prevent this. HTTP 202 is transient, not
a permanent block — we log it clearly and do NOT set is_banned=True.
"""

from __future__ import annotations

import logging
from urllib.parse import unquote, urlparse, parse_qs

from bs4 import BeautifulSoup

from engine_base import BaseEngine, SearchResult

logger = logging.getLogger('lead_engine.duckduckgo')

_LITE_BASE = 'https://lite.duckduckgo.com/lite/'
_MIN_PAGE_CHARS          = 1_000
_CHALLENGE_SIZE_THRESHOLD = 13_000


class DuckDuckGoEngine(BaseEngine):
    """DuckDuckGo Lite scraper — paginates via s= offset (step 25)."""

    name = 'duckduckgo'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._offset = 0

    def _first_page(self) -> dict:
        self._offset = 0
        # Origin header is required for DDG Lite POST requests;
        # its absence can contribute to HTTP 202 bot challenge responses.
        self._client.set_headers({
            'Referer': 'https://duckduckgo.com/',
            'Origin':  'https://duckduckgo.com',
        })
        return self._build_request()

    def _next_page(self, soup: BeautifulSoup) -> dict:
        # DDG Lite puts a next-page form at the bottom.
        # Find the LAST form with both q= and s= inputs (first is prev, last is next).
        forms     = soup.select('form[action]')
        next_form = None
        for f in reversed(forms):
            if f.select_one('input[name="s"]') and f.select_one('input[name="q"]'):
                next_form = f
                break

        if next_form:
            data  = {inp['name']: inp.get('value', '')
                     for inp in next_form.select('input[name]')}
            s_val = data.get('s', '')
            try:
                self._offset = int(s_val)
            except (ValueError, TypeError):
                self._offset += 25

            if data.get('q'):
                return {'url': _LITE_BASE, 'data': data}

        self._offset += 25
        if self._offset > 200:
            return {'url': None, 'data': None}
        return self._build_request()

    def _build_request(self) -> dict:
        return {
            'url': _LITE_BASE,
            'data': {
                'q':  self._query,
                's':  str(self._offset),
                'kl': 'wt-wt',
                'kp': '-1',
            },
        }

    def _parse_results(self, soup: BeautifulSoup) -> list[SearchResult]:
        page_text = soup.get_text(strip=True)

        if len(page_text) < _MIN_PAGE_CHARS:
            logger.warning('[duckduckgo] Page only %d chars — likely bot block', len(page_text))
            return []

        # HTTP 202 from DDG Lite = bot challenge page (transient, not a perm ban).
        # The page HTML still arrives but contains no result selectors.
        # Do NOT set is_banned — 202 resolves itself once the session is fresh.
        if getattr(self, '_last_status', 200) == 202:
            logger.warning(
                '[duckduckgo] HTTP 202 bot challenge — session was stale '
                '(warmup ran too long before this request). '
                'Re-run with a fresh warmup or increase inter-engine delay.'
            )
            return []

        if 'captcha' in page_text.lower() or 'select all squares' in page_text.lower():
            logger.warning('[duckduckgo] CAPTCHA detected on Lite endpoint')
            self.is_banned = True
            return []

        # Challenge pages are HTML but have no result anchors and are suspiciously small
        if len(page_text) < _CHALLENGE_SIZE_THRESHOLD and not soup.select('a.result-link'):
            logger.warning(
                '[duckduckgo] Page is small (%d chars) and has no result links — '
                'possible silent bot challenge. Check debug_html/duckduckgo_raw.html.',
                len(page_text)
            )
            return []

        results = self._parse_lite(soup)
        if not results:
            results = self._parse_html_fallback(soup)

        if not results:
            logger.warning('[duckduckgo] No results found — selector may have changed')
        else:
            logger.debug('[duckduckgo] Parsed %d results', len(results))

        return results

    def _parse_lite(self, soup: BeautifulSoup) -> list[SearchResult]:
        """
        DDG Lite result structure:
          a.result-link — title and URL for each result
          td.result-snippet — snippet (next sibling row)
        URLs in Lite are direct (no redirect wrapping).
        """
        results: list[SearchResult] = []
        seen: set[str] = set()

        link_tags = soup.select('a.result-link')
        if not link_tags:
            return []

        for a in link_tags:
            url = a.get('href', '').strip()
            if not url or not url.startswith('http'):
                continue
            url = _decode_ddg_url(url)
            if url in seen:
                continue
            seen.add(url)

            title = a.get_text(strip=True)

            snippet = ''
            row = a.find_parent('tr')
            if row:
                next_row = row.find_next_sibling('tr')
                if next_row:
                    snip_td = next_row.select_one('td.result-snippet')
                    if snip_td:
                        snippet = snip_td.get_text(strip=True)

            results.append(SearchResult(url=url, title=title, snippet=snippet))

        return results

    def _parse_html_fallback(self, soup: BeautifulSoup) -> list[SearchResult]:
        """
        Fallback: old html.duckduckgo.com selectors.
        Kept in case the Lite endpoint returns html-style markup.
        """
        items = []
        for sel in ('div.result.results_links_deep', 'div.result.web-result',
                    'div.result', 'article'):
            items = soup.select(sel)
            if items:
                break
        if not items:
            return []

        results = []
        for item in items:
            url = ''
            for a_sel in ('a.result__a[href]', 'h2 a[href]', 'a[href^="http"]'):
                tag = item.select_one(a_sel)
                if tag:
                    url = _decode_ddg_url(tag.get('href', ''))
                    break
            if not url or not url.startswith('http'):
                continue

            title_tag   = item.select_one('h2.result__title') or item.select_one('h2')
            snippet_tag = (item.select_one('a.result__snippet')
                           or item.select_one('.result__snippet'))

            results.append(SearchResult(
                url=url,
                title=self._text(title_tag),
                snippet=self._text(snippet_tag),
            ))
        return results


def _decode_ddg_url(url: str) -> str:
    """Decode DDG redirect wrappers (uddg= or u= params)."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if 'uddg' in params:
            return unquote(params['uddg'][0])
        if 'u' in params:
            return unquote(params['u'][0])
    except Exception:
        pass
    return url
