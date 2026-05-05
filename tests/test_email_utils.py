"""
tests.test_email_utils — Tests for email and phone extraction logic.
"""

import unittest

from core.email_utils import extract_emails_raw, extract_phones


class TestEmailUtils(unittest.TestCase):

    def test_mailto_query_string_stripped(self):
        """Verifies that query strings and URL fragments are stripped from email addresses."""
        html = 'Contact us at <a href="mailto:hello@example.co.uk?subject=test">hello@example.co.uk</a>'
        emails = extract_emails_raw(html)
        self.assertIn("hello@example.co.uk", emails)
        self.assertNotIn("hello@example.co.uk?subject=test", emails)

    def test_placeholder_domain_rejected(self):
        """Verifies that placeholder/filler email domains are rejected."""
        html = "Email: user@domain.com, real@company.com"
        emails = extract_emails_raw(html)
        self.assertIn("real@company.com", emails)
        self.assertNotIn("user@domain.com", emails)

    def test_placeholder_local_rejected(self):
        """Verifies that placeholder local parts (user@, john@, test@) are rejected."""
        html = "Email: john@validcompany.co.uk, info@validcompany.co.uk"
        emails = extract_emails_raw(html)
        self.assertIn("info@validcompany.co.uk", emails)
        self.assertNotIn("john@validcompany.co.uk", emails)

    def test_html_entity_phone_decoded(self):
        """Verifies that HTML-entity-encoded phone numbers are decoded correctly."""
        html = "Call us: &#x2B;44 207 123 4567"
        phones = extract_phones(html)
        # Should decode to +44 207 123 4567
        self.assertTrue(any("+44 207 123 4567" in p for p in phones))

    def test_decimal_phone_rejected(self):
        """Verifies that decimal numbers (prices) are not extracted as phone numbers."""
        html = "Price: 412 132.30, Phone: 020 7123 4567"
        phones = extract_phones(html)
        self.assertFalse(any("132.30" in p for p in phones))
        self.assertTrue(any("020 7123 4567" in p for p in phones))
        
    def test_zero_loop_phone_rejected(self):
        """Verifies that numbers containing three or more consecutive zeros are rejected."""
        html = "Fake: 020 7000 4567, Real: 020 7123 4567"
        phones = extract_phones(html)
        # 02070004567 contains 000
        self.assertFalse(any("020 7000 4567" in p for p in phones))
        self.assertTrue(any("020 7123 4567" in p for p in phones))

if __name__ == '__main__':
    unittest.main()
