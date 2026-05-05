"""
core.relevance — Query-keyword lead quality scoring.

Works for ANY query type — not just property management.
The system auto-expands the user's search query into keyword tokens and
scores the page body text against them, combined with real-business and
noise signals.

Public API
----------
score_relevance(html, query) — returns a dict with lead_quality,
                               keyword_match_pct, has_contact, has_about,
                               is_noise.

v1.1 fix
--------
The original implementation used "read more" as a news-article noise signal.
This fires on virtually every company website (service cards, team bios, blog
previews all use "read more" buttons) and caused real property management
companies with 100% keyword match to be classified as NOISE.

Fix: tightened noise patterns to dedicated job boards, directories, and news
articles.  More importantly: strong positive evidence (keyword_pct >= 40 AND
has_contact/has_services) now overrides noise signals, so a company page with
a careers section or blog widget is no longer discarded.
"""

from __future__ import annotations

import re

STOP_WORDS = {
    "the", "and", "for", "in", "of", "to", "a", "an", "with", "is",
    "are", "we", "our", "your", "that", "this", "it", "at", "on", "by",
}


def score_relevance(html: str, query: str) -> dict:
    """
    Score a page's HTML against the search query to determine lead quality.

    Algorithm
    ---------
    1. Auto-expand the query into keyword tokens (split on spaces, remove
       stop words, keep words >= 4 chars).
    2. Score the page body text for keyword matches.
    3. Detect real-business signals and noise signals.
    4. Classify: HOT > WARM > COLD, with NOISE only when noise signals are
       present AND strong positive evidence is absent.

    Quality levels
    --------------
    HOT   — keyword match >= 40% AND has contact/services signals.
    WARM  — keyword match >= 20% OR has an "About Us" section.
    COLD  — some presence but low keyword overlap.
    NOISE — dedicated job board, directory, or news article with no strong
            keyword evidence.

    Strong positive evidence (keyword_pct >= 40 AND has_contact/has_services)
    always overrides noise signals.
    """
    from bs4 import BeautifulSoup

    body = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()

    tokens = {
        w for w in re.findall(r"\b[a-z]{4,}\b", query.lower())
        if w not in STOP_WORDS
    }

    keyword_hits = sum(1 for t in tokens if t in body)
    keyword_pct  = round(keyword_hits / max(len(tokens), 1) * 100)

    # Real-business signals
    has_contact  = bool(re.search(
        r"contact\s+us|enquir|get\s+in\s+touch|reach\s+us|call\s+us", body
    ))
    has_about    = bool(re.search(
        r"about\s+us|our\s+team|who\s+we\s+are|founded\s+in|established", body
    ))
    has_services = bool(re.search(
        r"our\s+services|what\s+we\s+do|we\s+offer|we\s+provide|we\s+specialise", body
    ))

    # Noise signals — tightened in v1.1.
    # REMOVED: "read more" (ubiquitous UI pattern, not a news signal),
    #          "share this" (social buttons on company sites),
    #          "apply now" alone (company sites also hire).
    # KEPT: patterns that only appear on dedicated job boards, directories,
    #       or news articles with article metadata.

    # Dedicated job board: multiple overlapping job-listing signals required.
    is_job_board = bool(re.search(
        r"job\s+description.{0,200}(salary|per\s+annum)"
        r"|salary.{0,100}per\s+annum.{0,200}apply\s+now"
        r"|\bvacancies\b.{0,200}\bapply\b.{0,200}\bsalary\b",
        body,
    ))

    # Directory / aggregator listing page.
    is_directory = bool(re.search(
        r"showing\s+\d+\s+results"
        r"|sort\s+by.{0,60}filter\s+by"
        r"|\d+\s+businesses?\s+near"
        r"|compare\s+quotes\s+from\s+\d+",
        body,
    ))

    # News article (requires article metadata, not just "read more").
    is_news = bool(re.search(
        r"published\s+by\s+\w"
        r"|leave\s+a\s+comment"
        r"|related\s+articles"
        r"|comments?\s+\(\d+\)",
        body,
    ))

    is_noise = is_job_board or is_directory or is_news

    # Strong positive evidence overrides noise — a real company with a blog
    # or a hiring section is still a lead.
    strong_positive = keyword_pct >= 40 and (has_contact or has_services)

    if is_noise and not strong_positive:
        quality = "NOISE"
    elif keyword_pct >= 40 and (has_contact or has_services):
        quality = "HOT"
    elif keyword_pct >= 20 or has_about:
        quality = "WARM"
    else:
        quality = "COLD"

    return {
        "lead_quality":      quality,
        "keyword_match_pct": keyword_pct,
        "has_contact":       has_contact,
        "has_about":         has_about,
        "is_noise":          is_noise,
    }
