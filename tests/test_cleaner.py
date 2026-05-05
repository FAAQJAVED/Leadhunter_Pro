"""
tests.test_cleaner — Tests for DataCleaner and URL/domain utilities.
"""

import unittest

from pipeline.data_cleaner import DataCleaner, derive_name_from_domain


class MockResult:
    def __init__(self, url, title, snippet):
        self.url = url
        self.title = title
        self.snippet = snippet

class TestCleaner(unittest.TestCase):
    def setUp(self):
        self.cleaner = DataCleaner()

    def test_derive_name_from_domain(self):
        """Verifies that company names are correctly derived from domain strings.

        Note on thelondonmanagementcompany.com:
        Splitting an all-lowercase compound string ('thelondonmanagementcompany')
        into its constituent words requires a dictionary or NLP library — neither
        of which is available in the stdlib. The function produces the best
        possible output ('Thelondonmanagementcompany') which is still a large
        improvement over v1.0's SEO-title approach ("70 property manager job
        offers in London, Greater London"). CamelCase domains (JPropertyManagement)
        ARE correctly split because the uppercase boundaries survive the regex.
        """
        cases = {
            "chestertons.co.uk":              "Chestertons",
            "alpha-block-management.co.uk":   "Alpha Block Management",
            "thelondonmanagementcompany.com":  "Thelondonmanagementcompany",
            "JPropertyManagement.com":        "J Property Management",
        }
        for domain, expected in cases.items():
            with self.subTest(domain=domain):
                self.assertEqual(derive_name_from_domain(domain), expected)

    def test_directory_domain_produces_none(self):
        """Verifies that known directory/aggregator domains are hard-excluded and return None."""
        domains = ["yell.com", "yelp.com", "threebestrated.co.uk", "clutch.co"]
        for d in domains:
            res = MockResult(f"https://{d}/some-page", "Some Title", "Some Snippet")
            rec = self.cleaner.process(res, search_query="test", search_engine="test")
            self.assertIsNone(rec, f"Domain {d} should be excluded")

    def test_normalise_to_root_single_segment(self):
        """Verifies that URLs with any path segment are normalised to the root homepage."""
        url = "https://example.co.uk/property-management-london"
        res = MockResult(url, "Example", "Snippet")
        rec = self.cleaner.process(res, search_query="example", search_engine="bing")
        self.assertEqual(rec.website_url, "https://example.co.uk/")

    def test_geo_suspect_flag(self):
        """Verifies that domains with geo-suspect TLDs are flagged when configured."""
        from pipeline import data_cleaner
        data_cleaner.GEO_SUSPECT_TLDS = ['in']
        
        res = MockResult("https://example.in/", "Example", "Snippet")
        rec = self.cleaner.process(res, search_query="example", search_engine="bing")
        self.assertTrue(rec.flagged)
        self.assertEqual(rec.flag_reason, 'geo-suspect')
        self.assertLess(rec.score, 0)
        
        # Reset for other tests
        data_cleaner.GEO_SUSPECT_TLDS = []

    def test_irrelevance_flag(self):
        """Verifies flagging of irrelevant results based on title/query tokens."""
        res = MockResult("https://valid-site.com/", "Banana Peeling Services", "We peel bananas.")
        # Query about "Accountants" has no overlap with "Banana Peeling"
        rec = self.cleaner.process(res, search_query="London Accountants", search_engine="bing")
        self.assertTrue(rec.flagged)
        self.assertEqual(rec.flag_reason, 'irrelevant')

if __name__ == '__main__':
    unittest.main()
