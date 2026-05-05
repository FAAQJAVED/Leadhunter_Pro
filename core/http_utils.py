"""
core.http_utils — Lightweight HTTP fetching and Pass 1 enrichment.

All network calls go through ``fetch_url``, which enforces a hard
wall-clock timeout via a daemon thread (not just a socket timeout).
The daemon thread is abandoned — not killed — once the limit expires;
because it is a daemon it will not prevent process exit.

Public API
----------
fetch_url(url, cfg, wall_clock_limit)  — GET a URL, return HTML or None.
extract_company_name(html, fallback)   — Scrape company name from page HTML.
enrich_one_http(target, cfg)           — Pass 1: scrape email + phone + name via HTTP.
"""

from __future__ import annotations

import random
import re
import threading
import time
from typing import List, Optional, Tuple

import requests
import urllib3

from core.email_utils import (
    extract_emails_full,
    extract_phones,
    score_email,
    best_email,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Common title suffixes to strip when deriving company name from <title>.
# E.g. "Alpha Block Management | Home" → "Alpha Block Management"
_TITLE_STRIP_RE = re.compile(
    r"\s*[\|\-–—·•]\s*("
    r"home|welcome|about|contact|services|solutions|official\s+site|"
    r"homepage|main\s+page|index|default|property\s+management|"
    r"block\s+management|letting\s+agents?|estate\s+agents?"
    r").{0,60}$",
    re.I,
)
# Catch any trailing pipe/dash with filler text we didn't list above.
_TITLE_SEP_RE = re.compile(r"\s*[\|\-–—]\s*.{1,60}$")


def random_ua(cfg: dict) -> str:
    """Pick a random User-Agent string from the configured pool."""
    pool = cfg.get("user_agents", [])
    return random.choice(pool) if pool else "Mozilla/5.0"


def _rate_limit(cfg: dict) -> None:
    """Sleep for a random duration within the configured [min, max] range."""
    rl  = cfg.get("rate_limit", {})
    lo  = float(rl.get("min_seconds", 0.0))
    hi  = float(rl.get("max_seconds", 0.3))
    if hi > 0:
        time.sleep(random.uniform(lo, hi))


def _fetch_worker(url: str, ua: str, timeout: tuple, result: list) -> None:
    """
    Daemon-thread target: GET a single URL and append the response HTML
    to *result*.  Any exception is silently swallowed.
    """
    try:
        headers = {
            "User-Agent":      ua,
            "Accept":          "text/html,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
        if r.status_code < 400:
            result.append(r.text)
    except Exception:
        pass


def fetch_url(
    url: str,
    cfg: dict,
    wall_clock_limit: int = 10,
) -> Optional[str]:
    """
    Fetch *url* and return the response HTML, or ``None`` on failure/timeout.

    A daemon thread performs the actual network call so a truly stuck
    connection cannot block the main loop indefinitely regardless of the
    socket-level timeout.

    Parameters
    ----------
    url             : Fully-qualified URL to fetch.
    cfg             : Config dict — reads ``http_timeout`` and ``user_agents``.
    wall_clock_limit: Maximum seconds to wait for the thread (default 10).
    """
    result: list = []
    t = threading.Thread(
        target=_fetch_worker,
        args=(url, random_ua(cfg), tuple(cfg.get("http_timeout", [4, 6])), result),
        daemon=True,
    )
    t.start()
    try:
        t.join(timeout=wall_clock_limit)
    except KeyboardInterrupt:
        return None
    return result[0] if result else None


def extract_company_name(html: str, fallback: str = "") -> str:
    """
    Scrape the company's real name from their own page HTML.

    Priority order (most reliable first):
    1. ``<meta property="og:site_name">``  — explicitly set by the company,
       contains only the brand name, no page-title suffix.
    2. ``<title>`` tag with common suffixes stripped
       ("| Home", "- Property Management", etc.).
    3. ``<meta property="og:title">``  — fallback OG title, stripped.
    4. First ``<h1>`` tag — often the site name on simple sites.
    5. ``fallback``  — the domain-derived name from Phase 1.

    Parameters
    ----------
    html     : Homepage HTML string.
    fallback : Value to return if no better name can be extracted (usually
               the domain-derived name already in the target dict).

    Returns
    -------
    Cleaned company name string, never longer than 100 characters.
    """
    if not html:
        return fallback

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 1. og:site_name — best signal
        og_site = soup.find("meta", property="og:site_name")
        if og_site:
            name = (og_site.get("content") or "").strip()
            if name and len(name) <= 100:
                return name

        # 2. <title> tag — strip common page-type suffixes
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            cleaned = _TITLE_STRIP_RE.sub("", raw).strip()
            if not cleaned or cleaned == raw:
                # Try generic separator strip as fallback
                cleaned = _TITLE_SEP_RE.sub("", raw).strip()
            if cleaned and 2 < len(cleaned) <= 100:
                return cleaned

        # 3. og:title
        og_title = soup.find("meta", property="og:title")
        if og_title:
            raw = (og_title.get("content") or "").strip()
            cleaned = _TITLE_STRIP_RE.sub("", raw).strip()
            if not cleaned:
                cleaned = _TITLE_SEP_RE.sub("", raw).strip()
            if cleaned and 2 < len(cleaned) <= 100:
                return cleaned

        # 4. First <h1>
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(strip=True)
            if text and 2 < len(text) <= 80:
                return text

    except Exception:
        pass

    return fallback


def enrich_one_http(target: dict, cfg: dict) -> Tuple[str, str, str]:
    """
    Pass 1: attempt to find a contact email, phone, AND company name via HTTP.

    Visit sequence
    --------------
    1. Homepage (``target["website"]``).
    2. Each path in ``cfg["contact_paths"]`` in order.

    Early exit: stops fetching additional pages as soon as a high-quality
    email (score <= 2) is found.

    Parameters
    ----------
    target : Dict with keys ``"website"``, ``"name"``, ``"category"``, ``"phone"``.
    cfg    : Full config dict.

    Returns
    -------
    ``(best_email_str, best_phone_str, company_name)``

    ``company_name`` is the scraped name from the homepage HTML if found,
    otherwise ``""`` (caller falls back to the domain-derived name).
    Each field may be ``""`` if nothing was found.
    """
    base          = target["website"].rstrip("/")
    contact_paths = cfg.get("contact_paths", ["/contact", "/about"])
    emails: List[str] = []
    phones: List[str] = []
    company_name: str = ""

    html = fetch_url(base, cfg)
    if html:
        emails.extend(extract_emails_full(html))
        phones.extend(extract_phones(html))
        # Scrape the real company name from the homepage
        company_name = extract_company_name(html, fallback="")
    _rate_limit(cfg)

    if any(score_email(e, cfg) <= 2 for e in emails):
        return best_email(emails, cfg), phones[0] if phones else "", company_name

    for path in contact_paths:
        html = fetch_url(base + path, cfg)
        if html:
            found_emails = extract_emails_full(html)
            found_phones = extract_phones(html)
            emails.extend(found_emails)
            phones.extend(found_phones)
            if any(score_email(e, cfg) <= 2 for e in found_emails):
                break
        _rate_limit(cfg)

    return best_email(emails, cfg), phones[0] if phones else "", company_name
