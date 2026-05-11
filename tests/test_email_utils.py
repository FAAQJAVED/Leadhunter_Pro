"""
tests.test_email_utils — Tests for email and phone extraction logic.
"""

import unittest

from core.email_utils import (
    best_email,
    decode_cloudflare_email,
    extract_emails_raw,
    extract_phones,
    score_email,
)

# ---------------------------------------------------------------------------
# Minimal config matching config.example.yaml defaults used by score_email /
# best_email — enough to exercise all four score tiers without requiring a
# live config.yaml on disk.
# ---------------------------------------------------------------------------
_CFG = {
    "skip_email_keywords": [
        "noreply", "no-reply", "donotreply", "unsubscribe",
        "postmaster", "webmaster", "bounce",
    ],
    "generic_email_keywords": [
        "info", "admin", "hello", "contact", "enquiries", "enquiry",
        "office", "mail", "email", "team", "support", "help", "sales",
        "accounts", "finance", "general", "service", "post",
    ],
    "junk_email_domains": ["mailinator.com", "yopmail.com", "example.com"],
}


class TestEmailUtils(unittest.TestCase):

    # ── existing tests (unchanged) ──────────────────────────────────────────

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
        self.assertFalse(any("020 7000 4567" in p for p in phones))
        self.assertTrue(any("020 7123 4567" in p for p in phones))

    # ── NEW: decode_cloudflare_email ────────────────────────────────────────

    def test_decode_cloudflare_known_fixture(self):
        """Decodes a pre-computed Cloudflare hex string to its original address.

        Fixture derived from the XOR scheme: key=0x1a, plaintext=hello@example.com.
        Key byte prepended, all bytes hex-encoded → 36-char string.
        This exercises the full XOR-decode path without any network or browser.
        """
        encoded = "1a727f7676755a7f627b776a767f34797577"
        self.assertEqual(decode_cloudflare_email(encoded), "hello@example.com")

    def test_decode_cloudflare_invalid_hex_returns_empty(self):
        """Returns an empty string when the input is not valid hex."""
        self.assertEqual(decode_cloudflare_email("not-valid-hex!!"), "")
        self.assertEqual(decode_cloudflare_email(""), "")

    # ── NEW: score_email — all four tiers ───────────────────────────────────

    def test_score_email_tier_1_personal(self):
        """A personal-name local part scores 1 — highest quality, no generic keywords."""
        self.assertEqual(score_email("john.smith@realco.co.uk", _CFG), 1)

    def test_score_email_tiers_2_3_and_999(self):
        """Covers priority-generic (2), other-generic (3), and junk (999) in one method."""
        # Tier 2: exact priority set {"info","hello","contact","enquiries","enquiry"}
        self.assertEqual(score_email("info@realco.co.uk",    _CFG), 2)
        self.assertEqual(score_email("contact@realco.co.uk", _CFG), 2)

        # Tier 3: in generic_email_keywords but not in the tier-2 priority set
        self.assertEqual(score_email("support@realco.co.uk",  _CFG), 3)
        self.assertEqual(score_email("accounts@realco.co.uk", _CFG), 3)

        # Tier 999 via skip keyword in local part
        self.assertEqual(score_email("noreply@realco.co.uk",    _CFG), 999)

        # Tier 999 via junk domain regardless of local part
        self.assertEqual(score_email("info@mailinator.com",     _CFG), 999)

    # ── NEW: best_email ─────────────────────────────────────────────────────

    def test_best_email_returns_lowest_score(self):
        """best_email picks the candidate with the lowest score (highest quality)."""
        candidates = [
            "support@realco.co.uk",   # tier 3
            "info@realco.co.uk",      # tier 2
            "james.hunt@realco.co.uk", # tier 1 — should win
        ]
        self.assertEqual(best_email(candidates, _CFG), "james.hunt@realco.co.uk")

    def test_best_email_discards_junk_score_999(self):
        """Junk-scored (999) emails are excluded; best_email returns '' when all are junk."""
        # All junk — must return empty string
        all_junk = ["noreply@realco.co.uk", "info@mailinator.com"]
        self.assertEqual(best_email(all_junk, _CFG), "")

        # Mix of junk and valid — valid one must be returned
        mixed = ["noreply@realco.co.uk", "hello@realco.co.uk"]
        self.assertEqual(best_email(mixed, _CFG), "hello@realco.co.uk")


if __name__ == "__main__":
    unittest.main()