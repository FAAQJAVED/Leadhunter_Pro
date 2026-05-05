"""
tests/test_engines.py — Engine selector tests (offline, no network).
Runs with: python -m unittest discover  AND  pytest tests/

Fix notes (v1.1)
----------------
Each engine guards against bot-block / error pages by checking that the
full page text exceeds a minimum length:

  Mojeek  — get_text(strip=True) >= 300  chars
  Yahoo   — get_text(strip=True) >= 300  chars
  DDG     — get_text(strip=True) >= 1000 chars
  Bing    — description len     >  50   chars (for locale-pattern check)

The original test HTML constants were far below these thresholds (32, 14, 48,
and 46 chars respectively), so every _parse_results() call returned [] before
even looking at the HTML.

Fix: each HTML constant now includes a hidden padding <div> that pushes the
get_text() count above every threshold.  The div uses no class names that
any engine selector matches, so it does not interfere with result parsing.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from engine_base import SearchResult, _extract_base_domain
from engines.mojeek import MojeekEngine
from engines.duckduckgo import DuckDuckGoEngine
from engines.yahoo import YahooEngine, _extract_yahoo_url, _clean_yahoo_title
from engines.bing import BingEngine, _is_english_result


def _make_client():
    c = MagicMock()
    c.rotate_ua.return_value = "Mozilla/5.0"
    c.session = MagicMock()
    c.session.headers = {}
    c.session.cookies = MagicMock()
    return c


def _soup(html):
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# Padding block — pushes get_text(strip=True) length above 1 000 chars
# (the highest engine threshold, used by DDG).  The div has no class names
# that any engine selector targets, so it is invisible to result parsers.
# ---------------------------------------------------------------------------
_PAD = (
    '<div id="page-pad" style="display:none">'
    + "Search results content. " * 50
    + "</div>"
)


# ---------------------------------------------------------------------------
# Test HTML fixtures (padded)
# ---------------------------------------------------------------------------

MOJEEK_HTML = f"""<html><body>{_PAD}
<li><h2><a href="https://www.acme-letting.co.uk/">Acme</a></h2>
    <a class="ob" href="https://www.acme-letting.co.uk/">acme</a>
    <p class="s">block mgmt</p></li>
<li><h2><a href="https://www.block-pros.com/">BPros</a></h2>
    <a class="ob" href="https://www.block-pros.com/">bpros</a>
    <p class="s">mgmt</p></li>
</body></html>"""

DDG_HTML = f"""<html><body>{_PAD}<table>
<tr><td><a class="result-link" href="https://letting-uk.co.uk/">LUK</a></td></tr>
<tr><td class="result-snippet">Expert letting agents.</td></tr>
<tr><td><a class="result-link" href="https://propmgr.co.uk/">PM</a></td></tr>
<tr><td class="result-snippet">Block specialists.</td></tr>
</table></body></html>"""

YAHOO_HTML = f"""<html><body>{_PAD}<ol>
<li><div class="compTitle">
  <a href="https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fblockmgmt.co.uk%2F/RK=2/">BlockMgmt</a>
</div></li>
<li><div class="compTitle">
  <h3><a href="https://r.search.yahoo.com/_ylt=y/RU=https%3A%2F%2Fresidential-pm.co.uk%2F/RK=2/">ResPM</a></h3>
</div></li>
</ol></body></html>"""

BING_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Block Management London</title><link>https://blockmanagement.co.uk/</link>
<description>Leading block management in London.</description></item>
<item><title>Residential Property Managers</title><link>https://residentialpm.co.uk/</link>
<description>Expert property management.</description></item>
</channel></rss>"""


# ---------------------------------------------------------------------------
# Tests: _extract_base_domain
# ---------------------------------------------------------------------------

class TestExtractBaseDomain(unittest.TestCase):
    def test_strips_www(self):
        self.assertEqual(_extract_base_domain("https://www.example.com/path"), "example.com")

    def test_no_www(self):
        self.assertEqual(_extract_base_domain("https://example.co.uk/"), "example.co.uk")

    def test_empty(self):
        self.assertEqual(_extract_base_domain(""), "")

    def test_strips_port(self):
        self.assertEqual(_extract_base_domain("http://example.com:8080/"), "example.com")

    def test_lowercases(self):
        self.assertEqual(_extract_base_domain("https://EXAMPLE.COM/"), "example.com")


# ---------------------------------------------------------------------------
# Tests: MojeekEngine
# ---------------------------------------------------------------------------

class TestMojeekEngine(unittest.TestCase):
    def setUp(self):
        self.engine = MojeekEngine(client=_make_client())

    def test_a_ob_finds_results(self):
        results = self.engine._parse_results(_soup(MOJEEK_HTML))
        self.assertEqual(len(results), 2)
        self.assertIn("acme-letting.co.uk", {r.domain for r in results})

    def test_returns_search_result_objects(self):
        for r in self.engine._parse_results(_soup(MOJEEK_HTML)):
            self.assertIsInstance(r, SearchResult)
            self.assertTrue(r.url.startswith("http"))

    def test_deduplicates_same_domain(self):
        html = f"""<html><body>{_PAD}
        <a class="ob" href="https://example.com/">x</a>
        <a class="ob" href="https://example.com/about">y</a>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertEqual([r.domain for r in results].count("example.com"), 1)

    def test_skips_mojeek_internal(self):
        html = f"""<html><body>{_PAD}
        <a class="ob" href="https://www.mojeek.com/search?q=x">M</a>
        <a class="ob" href="https://real.co.uk/">R</a>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertTrue(all("mojeek.com" not in r.url for r in results))

    def test_empty_page(self):
        self.assertEqual(
            self.engine._parse_results(_soup("<html><body></body></html>")), []
        )


# ---------------------------------------------------------------------------
# Tests: DuckDuckGoEngine
# ---------------------------------------------------------------------------

class TestDuckDuckGoEngine(unittest.TestCase):
    def setUp(self):
        self.engine = DuckDuckGoEngine(client=_make_client())
        self.engine._last_status = 200

    def test_finds_result_links(self):
        self.assertEqual(len(self.engine._parse_results(_soup(DDG_HTML))), 2)

    def test_http_202_returns_empty(self):
        self.engine._last_status = 202
        self.assertEqual(self.engine._parse_results(_soup(DDG_HTML)), [])

    def test_too_short_returns_empty(self):
        self.assertEqual(
            self.engine._parse_results(_soup("<html><body>x</body></html>")), []
        )

    def test_deduplicates(self):
        html = f"""<html><body>{_PAD}
        <a class="result-link" href="https://same.com/">A</a>
        <a class="result-link" href="https://same.com/p2">B</a>
        <a class="result-link" href="https://other.com/">C</a>
        </body></html>"""
        urls = [r.url for r in self.engine._parse_results(_soup(html))]
        self.assertEqual(len(urls), len(set(urls)))


# ---------------------------------------------------------------------------
# Tests: Yahoo URL extraction helpers
# ---------------------------------------------------------------------------

class TestYahooUrlExtraction(unittest.TestCase):
    def test_extracts_from_ru(self):
        self.assertEqual(
            _extract_yahoo_url(
                "https://r.search.yahoo.com/_ylt=abc/RU=https%3A%2F%2Fexample.co.uk%2F/RK=2/"
            ),
            "https://example.co.uk/",
        )

    def test_direct_url(self):
        self.assertEqual(
            _extract_yahoo_url("https://example.co.uk/"), "https://example.co.uk/"
        )

    def test_rejects_yahoo(self):
        self.assertEqual(
            _extract_yahoo_url("https://search.yahoo.com/search?q=x"), ""
        )

    def test_empty(self):
        self.assertEqual(_extract_yahoo_url(""), "")


class TestCleanYahooTitle(unittest.TestCase):
    def test_strips_url_bleeding(self):
        self.assertEqual(
            _clean_yahoo_title("Acme https://acme.co.uk › about"), "Acme"
        )

    def test_strips_breadcrumb(self):
        self.assertEqual(_clean_yahoo_title("Acme › Property"), "Acme")

    def test_strips_whitespace(self):
        self.assertEqual(_clean_yahoo_title("  Acme  "), "Acme")


# ---------------------------------------------------------------------------
# Tests: YahooEngine
# ---------------------------------------------------------------------------

class TestYahooEngine(unittest.TestCase):
    def setUp(self):
        self.engine = YahooEngine(client=_make_client())

    def test_pattern_a(self):
        results = self.engine._parse_results(_soup(YAHOO_HTML))
        self.assertIn("blockmgmt.co.uk", {r.domain for r in results})

    def test_pattern_b_h3_wrapped(self):
        results = self.engine._parse_results(_soup(YAHOO_HTML))
        self.assertIn("residential-pm.co.uk", {r.domain for r in results})

    def test_no_url_bleeding_in_titles(self):
        html = f"""<html><body>{_PAD}<div class="compTitle">
        <a href="https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fex.co.uk%2F/RK=2/">
        Example https://www.ex.co.uk › about</a></div></body></html>"""
        for r in self.engine._parse_results(_soup(html)):
            self.assertNotIn("https://", r.title)

    def test_per_domain_sitelink_dedup(self):
        html = f"""<html><body>{_PAD}
        <div class="compTitle">
          <a href="https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fsame.co.uk%2F/RK=2/">A</a>
        </div>
        <div class="compTitle">
          <a href="https://r.search.yahoo.com/_ylt=y/RU=https%3A%2F%2Fsame.co.uk%2Fabout/RK=2/">B</a>
        </div>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertEqual([r.domain for r in results].count("same.co.uk"), 1)


# ---------------------------------------------------------------------------
# Tests: Bing _is_english_result
# ---------------------------------------------------------------------------

class TestBingIsEnglish(unittest.TestCase):
    def test_english_passes(self):
        self.assertTrue(_is_english_result("Block Management London", "Services"))

    def test_non_ascii_title_rejected(self):
        self.assertFalse(_is_english_result("Блок Управление Москва"))

    def test_locale_in_description_rejected(self):
        # Description must be > 50 chars for the locale-pattern guard to fire.
        # "example.com/de/ for German customers long description text" = 59 chars.
        self.assertFalse(
            _is_english_result(
                "Name",
                "example.com/de/ for German customers long description text",
            )
        )

    def test_empty_passes(self):
        self.assertTrue(_is_english_result(""))


# ---------------------------------------------------------------------------
# Tests: BingEngine RSS parsing
# ---------------------------------------------------------------------------

class TestBingEngine(unittest.TestCase):
    def setUp(self):
        self.engine = BingEngine(client=_make_client())

    def test_rss_extracts_urls(self):
        _, results = self.engine._parse_rss(BING_RSS)
        self.assertIn(
            "https://blockmanagement.co.uk/", [r.url for r in results]
        )

    def test_rss_returns_results(self):
        _, results = self.engine._parse_rss(BING_RSS)
        self.assertGreaterEqual(len(results), 1)

    def test_invalid_xml_returns_empty(self):
        count, results = self.engine._parse_rss("not xml at all")
        self.assertEqual(results, [])
        self.assertEqual(count, 0)

    def test_geo_filters_non_english(self):
        xml = """<?xml version="1.0"?><rss><channel><item>
        <title>Résultats français éàùîô</title><link>https://fr.fr/</link>
        <description>/fr/ German locale hl=de lang=de language=de long text here</description>
        </item></channel></rss>"""
        _, results = self.engine._parse_rss(xml)
        self.assertEqual(len(results), 0)


# ---------------------------------------------------------------------------
# Additional selector-breakage guards (Task 8b)
# Each test feeds a minimal HTML snippet through the engine's parsing logic
# and asserts the expected URL is returned.  A failing test here means a
# CSS selector or XPath changed upstream — update the engine, not the test.
# ---------------------------------------------------------------------------

class TestMojeekSelectorGuards(unittest.TestCase):
    """Guards against Mojeek HTML selector breakage."""

    def setUp(self):
        self.engine = MojeekEngine(client=_make_client())

    def test_ob_class_anchor_is_primary_selector(self):
        """The primary Mojeek selector targets <a class="ob"> for URLs."""
        html = f"""<html><body>{_PAD}
        <li>
          <h2><a href="https://primaryco.com/">Primary Co</a></h2>
          <a class="ob" href="https://primaryco.com/">primaryco.com</a>
          <p class="s">Description text here</p>
        </li>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertTrue(any("primaryco.com" in r.url for r in results))

    def test_title_extracted_from_h2(self):
        """Mojeek titles come from the <h2> anchor, not the ob anchor."""
        html = f"""<html><body>{_PAD}
        <li>
          <h2><a href="https://titletest.com/">The Title Here</a></h2>
          <a class="ob" href="https://titletest.com/">titletest.com</a>
        </li>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertTrue(any(r.title == "The Title Here" for r in results))


class TestDuckDuckGoSelectorGuards(unittest.TestCase):
    """Guards against DuckDuckGo HTML selector breakage."""

    def setUp(self):
        self.engine = DuckDuckGoEngine(client=_make_client())
        self.engine._last_status = 200

    def test_result_link_class_is_selector(self):
        """DDG parser targets <a class='result-link'>."""
        html = f"""<html><body>{_PAD}
        <a class="result-link" href="https://selectorcheck.co.uk/">SelectorCheck</a>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertTrue(any("selectorcheck.co.uk" in r.url for r in results))

    def test_non_result_link_anchor_ignored(self):
        """Anchors without class='result-link' must not be returned."""
        html = f"""<html><body>{_PAD}
        <a href="https://shouldbeignored.com/">Nav link</a>
        <a class="result-link" href="https://shouldbefound.com/">Result</a>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        urls = [r.url for r in results]
        self.assertFalse(any("shouldbeignored.com" in u for u in urls))
        self.assertTrue(any("shouldbefound.com" in u for u in urls))


class TestYahooSelectorGuards(unittest.TestCase):
    """Guards against Yahoo HTML selector breakage."""

    def setUp(self):
        self.engine = YahooEngine(client=_make_client())

    def test_compTitle_div_selector(self):
        """Yahoo parser targets <div class='compTitle'> containing an anchor."""
        html = f"""<html><body>{_PAD}
        <div class="compTitle">
          <a href="https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fselguard.co.uk%2F/RK=2/">
            SelGuard
          </a>
        </div>
        </body></html>"""
        results = self.engine._parse_results(_soup(html))
        self.assertTrue(any("selguard.co.uk" in r.url for r in results))

    def test_encoded_ru_param_decoded_correctly(self):
        """The RU= URL-encoded param must be decoded to the real destination."""
        raw = "https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fdecodecheck.co.uk%2F/RK=2/"
        self.assertEqual(_extract_yahoo_url(raw), "https://decodecheck.co.uk/")


class TestBingSelectorGuards(unittest.TestCase):
    """Guards against Bing RSS selector breakage."""

    def setUp(self):
        self.engine = BingEngine(client=_make_client())

    def test_link_element_extracted(self):
        """Bing parser reads <link> from each RSS <item>."""
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
        <item>
          <title>Link Guard Test</title>
          <link>https://linkguard.co.uk/</link>
          <description>Long enough description to pass the English guard check here.</description>
        </item>
        </channel></rss>"""
        _, results = self.engine._parse_rss(xml)
        self.assertTrue(any("linkguard.co.uk" in r.url for r in results))

    def test_empty_channel_returns_zero(self):
        """An RSS feed with no items returns count=0 and empty list."""
        xml = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""
        count, results = self.engine._parse_rss(xml)
        self.assertEqual(count, 0)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
