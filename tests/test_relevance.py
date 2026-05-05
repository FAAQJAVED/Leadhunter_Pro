"""
tests/test_relevance.py — Lead quality scoring tests (CHANGE 5).
Runs with: python -m unittest discover  AND  pytest tests/
"""
from __future__ import annotations
import unittest
from core.relevance import score_relevance

HOT_HTML = """<html><body>
<h1>Block Management Services Manchester</h1>
<p>We are a leading block management company based in Manchester.</p>
<p>Our block management services cover residential and commercial properties.</p>
<p>Contact us today to discuss your block management requirements.</p>
<p>We offer comprehensive block management solutions tailored to your needs.</p>
</body></html>"""

WARM_HTML = """<html><body>
<h1>About Us</h1>
<p>Established in 2005, we are a professional property services company.</p>
<p>Our team of experienced professionals delivers high-quality results.</p>
<p>Who we are: a dedicated group of property specialists.</p>
</body></html>"""

COLD_HTML = """<html><body>
<h1>Welcome</h1><p>We provide various professional services.</p>
<p>Please get in touch if you have any questions.</p>
</body></html>"""

NOISE_JOB = """<html><body>
<h1>Block Manager — Job Vacancy</h1>
<p>Apply now. Job description: block management required.</p>
<p>Salary: £35,000 per annum. Vacancies available across the UK.</p>
</body></html>"""

NOISE_DIR = """<html><body>
<h1>Block Management Companies Near You</h1>
<p>Showing 47 results. Sort by: rating | distance</p>
<p>Filter by: location | price. 47 businesses near Manchester.</p>
</body></html>"""

NOISE_NEWS = """<html><body>
<h1>The Future of Block Management</h1>
<p>Published by: Property Week. Read more. Share this article.</p>
<p>Leave a comment. Related articles: Leasehold reform.</p>
</body></html>"""

QUERY = "block management Manchester"

class TestLeadQuality(unittest.TestCase):
    def test_hot(self): self.assertEqual(score_relevance(HOT_HTML, QUERY)["lead_quality"], "HOT")
    def test_warm(self): self.assertEqual(score_relevance(WARM_HTML, QUERY)["lead_quality"], "WARM")
    def test_cold(self): self.assertEqual(score_relevance(COLD_HTML, QUERY)["lead_quality"], "COLD")
    def test_noise_job(self):
        r = score_relevance(NOISE_JOB, QUERY)
        self.assertEqual(r["lead_quality"], "NOISE"); self.assertTrue(r["is_noise"])
    def test_noise_directory(self):
        r = score_relevance(NOISE_DIR, QUERY)
        self.assertEqual(r["lead_quality"], "NOISE"); self.assertTrue(r["is_noise"])
    def test_noise_news(self):
        r = score_relevance(NOISE_NEWS, QUERY)
        self.assertEqual(r["lead_quality"], "NOISE"); self.assertTrue(r["is_noise"])

class TestKeywordMatch(unittest.TestCase):
    def test_high_match_for_hot(self): self.assertGreaterEqual(score_relevance(HOT_HTML, QUERY)["keyword_match_pct"], 40)
    def test_zero_match_irrelevant(self):
        html = "<html><body><p>Python programming tutorials for beginners.</p></body></html>"
        self.assertEqual(score_relevance(html, QUERY)["keyword_match_pct"], 0)
    def test_between_0_and_100(self):
        pct = score_relevance(HOT_HTML, QUERY)["keyword_match_pct"]
        self.assertGreaterEqual(pct, 0); self.assertLessEqual(pct, 100)

class TestRealBusinessSignals(unittest.TestCase):
    def test_has_contact(self):
        html = "<html><body><p>Contact us today for a free quote.</p></body></html>"
        self.assertTrue(score_relevance(html, "letting agents London")["has_contact"])
    def test_has_about(self):
        html = "<html><body><h2>About Us</h2><p>Founded in 1995.</p></body></html>"
        self.assertTrue(score_relevance(html, "letting agents London")["has_about"])
    def test_empty_page_no_signals(self):
        r = score_relevance("<html><body></body></html>", "block management")
        self.assertFalse(r["has_contact"]); self.assertFalse(r["has_about"])
        self.assertFalse(r["is_noise"])

class TestReturnStructure(unittest.TestCase):
    KEYS = ("lead_quality","keyword_match_pct","has_contact","has_about","is_noise")
    def test_all_keys_present(self):
        r = score_relevance(HOT_HTML, "block management")
        for k in self.KEYS: self.assertIn(k, r)
    def test_lead_quality_valid_string(self):
        self.assertIn(score_relevance(HOT_HTML, "block management")["lead_quality"],
                      ("HOT","WARM","COLD","NOISE"))
    def test_pct_is_int(self):
        self.assertIsInstance(score_relevance(WARM_HTML, "block management")["keyword_match_pct"], int)
    def test_booleans_are_bool(self):
        r = score_relevance(COLD_HTML, "block management")
        self.assertIsInstance(r["has_contact"], bool); self.assertIsInstance(r["has_about"], bool)

class TestEdgeCases(unittest.TestCase):
    def test_empty_html(self):
        r = score_relevance("", QUERY)
        self.assertIn(r["lead_quality"], ("HOT","WARM","COLD","NOISE"))
        self.assertEqual(r["keyword_match_pct"], 0)
    def test_empty_query(self):
        r = score_relevance(HOT_HTML, "")
        self.assertIsInstance(r["lead_quality"], str)
    def test_works_any_industry(self):
        html = """<html><body><h1>Dental Practice Manchester</h1>
        <p>Our dental team offers NHS and private dental services.</p>
        <p>Contact us to book your dental appointment today.</p></body></html>"""
        r = score_relevance(html, "dental practice Manchester")
        self.assertIn(r["lead_quality"], ("HOT","WARM"))
    def test_noise_beats_keyword_match(self):
        html = """<html><body>
        <p>block management Manchester jobs</p>
        <p>Apply now. Job description: block manager role.</p>
        <p>Salary £30,000 per annum. Vacancies available.</p></body></html>"""
        self.assertEqual(score_relevance(html, QUERY)["lead_quality"], "NOISE")

if __name__ == "__main__": unittest.main()
