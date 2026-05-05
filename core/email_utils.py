"""
core.email_utils — Email and phone extraction, decoding, and scoring.

Public API
----------
extract_emails_raw(html)     — regex-only email extraction with placeholder filtering.
decode_cloudflare_email(enc) — decode a Cloudflare XOR-encoded hex string.
extract_emails_full(html)    — regex + Cloudflare decoding combined.
extract_phones(html)         — phone number extraction with entity decoding and junk rejection.
score_email(email, cfg)      — quality score: 1=personal, 2=priority-generic,
                               3=generic, 999=junk/skip.
best_email(emails, cfg)      — pick the single best email from a list.
"""

from __future__ import annotations

import html as html_module
import re
from typing import List, Set


# ---------------------------------------------------------------------------
# Placeholder domain and local-part blocklists — rejects template/filler addresses
# ---------------------------------------------------------------------------

_PLACEHOLDER_DOMAINS = frozenset({
    'domain.com', 'email.com', 'example.com', 'example.org', 'example.net',
    'doe.com', 'test.com', 'placeholder.com', 'godaddy.com', 'wix.com',
    'weebly.com', 'squarespace.com', 'wordpress.com', 'mailinator.com',
    'yopmail.com', 'tempmail.com', 'guerrillamail.com', 'sharklasers.com',
    'trashmail.com',
})

_PLACEHOLDER_LOCALS = frozenset({
    'user', 'username', 'yourname', 'your.name', 'john', 'jane', 'firstname',
    'name', 'test', 'demo', 'filler', 'placeholder', 'sample', 'noreply',
    'email', 'mail',
})


def extract_emails_raw(html: str) -> List[str]:
    """
    Extract plaintext email addresses from HTML using a permissive regex.

    False-positive reduction:
      - Strip mailto query strings (?subject=…) and URL fragments (#).
      - Reject addresses from known placeholder domains.
      - Reject addresses whose local part is a known placeholder token.
      - Strip leading/trailing punctuation.
      - Reject addresses that contain asset-file extensions (.png, .js, …).
      - Reject addresses longer than 80 characters.
      - Validate final structure with a stricter pattern.

    Returns a deduplicated list of lowercased email strings.
    """
    raw = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", html)
    result: List[str] = []
    for e in raw:
        e = e.lower().strip().strip('.,;"\'')

        # Strip mailto query strings and URL fragments before validation
        e = e.split('?')[0]
        e = e.split('#')[0]

        if not re.match(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", e):
            continue

        parts = e.split('@', 1)
        if len(parts) != 2:
            continue
        local, domain = parts

        # Reject placeholder domains (template/website-builder default addresses)
        if domain in _PLACEHOLDER_DOMAINS:
            continue

        # Reject placeholder local parts (e.g. john@, user@, test@)
        if local in _PLACEHOLDER_LOCALS:
            continue

        if any(ext in e for ext in [".png", ".jpg", ".svg", ".gif", ".css", ".js"]):
            continue
        if len(e) > 80:
            continue
        result.append(e)
    return list(set(result))


def decode_cloudflare_email(encoded: str) -> str:
    """
    Decode a Cloudflare email-protection hex string.

    Cloudflare's cdn-cgi email-protection scheme XORs every byte of the
    plaintext email against the first byte of the ciphertext (the key),
    then hex-encodes the entire result (key byte first).

    Parameters
    ----------
    encoded : Hex string, e.g. ``"1a727f7676755a7f627b776a767f34797577"``

    Returns
    -------
    Decoded email string, or ``""`` if decoding fails.

    Example
    -------
    >>> decode_cloudflare_email("1a727f7676755a7f627b776a767f34797577")
    'hello@example.com'
    """
    try:
        enc = bytes.fromhex(encoded)
        key = enc[0]
        return "".join(chr(b ^ key) for b in enc[1:])
    except Exception:
        return ""


def extract_emails_full(html: str) -> List[str]:
    """
    Extract all email addresses from HTML, including Cloudflare-obfuscated ones.

    Two Cloudflare patterns are handled:
      1. ``/cdn-cgi/l/email-protection#<hex>``   (href-based)
      2. ``data-cfemail="<hex>"``                 (attribute-based)

    Query strings and fragments are stripped from Cloudflare-decoded
    addresses as well (a mailto: on a CF-protected site can still carry ?subject=).

    Returns a deduplicated list of lowercased email strings.
    """
    emails = extract_emails_raw(html)

    # Note: the capture group in the second pattern closes BEFORE the final quote.
    # Incorrect: r'data-cfemail="([a-f0-9]+")'   ← quote inside group, wrong
    # Correct:   r'data-cfemail="([a-f0-9]+)"'   ← quote outside group
    cloudflare_patterns = (
        r"/cdn-cgi/l/email-protection#([a-f0-9]+)",
        r'data-cfemail="([a-f0-9]+)"',
    )
    for pattern in cloudflare_patterns:
        for m in re.finditer(pattern, html):
            decoded = decode_cloudflare_email(m.group(1))
            if "@" in decoded:
                # Strip query strings from Cloudflare-decoded addresses too
                decoded = decoded.split('?')[0].split('#')[0]
                emails.append(decoded.lower().strip())

    return list(set(emails))


def extract_phones(html: str) -> List[str]:
    """
    Extract phone numbers from HTML.

    Robustness measures applied:
      - HTML entities are decoded before extraction (&#x2B; → +).
      - Strings containing a decimal point followed by digits (e.g. 132.305)
        are rejected as prices/reference numbers, not phone numbers.
      - Digit strings containing three or more consecutive zeros (000) are
        rejected as placeholder numbers (e.g. 000-000-0000, test data).

    Strategy (priority order):
      1. ``tel:`` href attributes — highest confidence, very low false-positive rate.
      2. Regex pattern matching — broader sweep filtered by digit count (7–15).

    Returns a deduplicated list of raw phone strings ordered most-reliable first.
    Digit sequences are deduplicated (same number expressed differently appears once).
    """
    # Decode HTML entities before extraction (e.g. &#x2B;44 → +44)
    html_str = html_module.unescape(html)

    seen_digits: Set[str] = set()
    phones: List[str] = []

    def _add(raw: str) -> None:
        """
        Validate and add a candidate phone string.

        Rejects:
          - Strings with a decimal point followed by digits (price/ref number).
          - Digit strings with three or more consecutive zeros (placeholder).
          - Strings outside 7–15 digit range.
          - Duplicates (same digit sequence already seen).
        """
        raw = raw.strip()

        # Reject prices: a decimal point followed by digits is never a phone number
        if re.search(r'\.\d', raw):
            return

        digits = re.sub(r"\D", "", raw)

        # Reject placeholder numbers: three or more consecutive zeros indicates filler
        # signals test/dummy data (e.g. 000-000-0000, 0800-000-0000 style fillers)
        if "000" in digits:
            return

        if 7 <= len(digits) <= 15 and digits not in seen_digits:
            seen_digits.add(digits)
            phones.append(raw)

    for m in re.finditer(r'href=["\'`]tel:([^"\'`]{4,25})["\'`]', html_str, re.I):
        _add(m.group(1).replace("%20", " "))

    if not phones:
        patterns = [
            r"\+\d{1,3}[\s\-\.]?\(?\d{1,4}\)?[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}",
            r"\(\d{2,5}\)[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}",
            r"\b\d{3,5}[\s\-\.]\d{3,4}[\s\-\.]\d{3,4}\b",
        ]
        for pat in patterns:
            for m in re.finditer(pat, html_str):
                _add(m.group(0))

    return phones


def score_email(email: str, cfg: dict) -> int:
    """
    Score an email address by contact quality. **Lower score = better.**

    Score   Meaning
    -----   -------
      1     Personal name address  (e.g. john.smith@company.com)
      2     High-priority generic  (info@, hello@, contact@, enquiries@, enquiry@)
      3     Other generic          (support@, accounts@, sales@, manager@, …)
    999     Junk / skip-list       — filtered out entirely
    """
    if not email or "@" not in email:
        return 999

    parts  = email.lower().split("@", 1)
    local  = parts[0]
    domain = parts[1]

    skip_kws     = set(cfg.get("skip_email_keywords",   []))
    generic_kws  = set(cfg.get("generic_email_keywords", []))
    junk_domains = set(cfg.get("junk_email_domains",     []))

    if any(k in local  for k in skip_kws):     return 999
    if any(j in domain for j in junk_domains): return 999
    if not any(k in local for k in generic_kws): return 1
    if local in {"info", "hello", "contact", "enquiries", "enquiry"}: return 2
    return 3


def best_email(emails: List[str], cfg: dict) -> str:
    """
    Return the single highest-quality email from a list.

    Emails scored 999 (junk/skip) are excluded entirely.
    Among the remaining candidates the one with the lowest score is returned.
    Returns ``""`` if the list is empty or all candidates are junk.
    """
    scored = [
        (e.lower().strip(), score_email(e, cfg))
        for e in emails
        if e and "@" in e
    ]
    valid = [(e, s) for e, s in scored if s < 999]
    if not valid:
        return ""
    return min(valid, key=lambda x: x[1])[0]
