"""
core.browser_utils — Playwright headless browser helpers.

**Critical invariant (Windows compatibility)**
The ``sync_playwright()`` context manager must NEVER be used as a ``with``
statement inside this module.  The caller (``enricher.run_pass2``) is
responsible for the lifecycle:

    pw = sync_playwright().__enter__()
    try:
        browser, page = launch_browser(pw, cfg)
        …
    finally:
        pw.__exit__(None, None, None)

This pattern is required because ``with sync_playwright() as p:`` raises
an obscure ``ContextVar`` error in some Windows + Python 3.12 environments.

Public API
----------
launch_browser(p, cfg)                — start Chromium, return (browser, page).
dismiss_cookie_banner(page, cfg)      — silently click a cookie-consent button.
enrich_one_browser(page, target, cfg) — Pass 2: scrape email + phone via browser.
"""

from __future__ import annotations

import time

from core._log import log
from core.email_utils import (
    best_email,
    extract_emails_full,
    extract_phones,
    score_email,
)
from core.http_utils import _rate_limit, random_ua

# Resource patterns blocked in the browser context to reduce bandwidth
# and speed up page loads.  Map tile images are intentionally NOT blocked
# so that map-heavy contact pages still render their embedded content.
_BLOCKED_RESOURCES = [
    "**/*.{png,jpg,jpeg,gif,svg,webp,ico,woff,woff2,ttf,eot,mp4,mp3}",
    "**/google-analytics**",
    "**/googletagmanager**",
    "**/doubleclick**",
    "**/facebook.net/en_US/fbevents**",
    "**/connect.facebook.net**",
]


def launch_browser(p, cfg: dict):  # noqa: ANN001
    """
    Launch a headless Chromium instance with tracking routes blocked.

    Retries up to 3 times (with a 3-second pause between attempts) before
    raising ``RuntimeError``.

    Parameters
    ----------
    p   : A ``sync_playwright()`` handle obtained via ``__enter__()``.
    cfg : Config dict — reads ``locale`` and ``user_agents``.

    Returns
    -------
    ``(browser, page)`` tuple ready for use.
    """
    ua     = random_ua(cfg)
    locale = cfg.get("locale", "en-US")

    for attempt in range(3):
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--mute-audio",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                ],
            )
            ctx = browser.new_context(
                user_agent=ua,
                locale=locale,
                ignore_https_errors=True,
            )
            for pattern in _BLOCKED_RESOURCES:
                ctx.route(pattern, lambda route: route.abort())
            page = ctx.new_page()
            return browser, page
        except Exception as exc:
            log(f"Browser launch attempt {attempt + 1}/3 failed: {exc}", "warn")
            time.sleep(3)

    raise RuntimeError("Chromium failed to launch after 3 attempts.")


def dismiss_cookie_banner(page, cfg: dict) -> None:  # noqa: ANN001
    """
    Silently attempt to click any recognised cookie-consent button.

    Tries each selector from ``cfg["cookie_selectors"]`` in order and
    returns after the first successful click.  All errors are swallowed
    — a failed dismiss is not a scraping failure.
    """
    for sel in cfg.get("cookie_selectors", []):
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=800)
                time.sleep(0.15)
                return
        except Exception:
            pass


def enrich_one_browser(page, target: dict, cfg: dict) -> tuple[str, str]:
    """
    Pass 2: find a contact email **and** phone using a Playwright-rendered page.

    Useful for sites that require JavaScript execution before contact
    details appear in the DOM (React / Angular / Next.js SPAs, etc.).

    Visit sequence
    --------------
    1. Homepage — cookie banner is dismissed here.
    2. Up to two contact sub-pages from ``cfg["contact_paths"]``.

    Early exit: stops visiting additional pages once a high-quality email
    (score ≤ 2) is found.

    Parameters
    ----------
    page   : A live Playwright ``Page`` object (shared across calls for speed).
    target : Dict with keys ``"website"``, ``"name"``, ``"category"``, ``"phone"``.
    cfg    : Full config dict.

    Returns
    -------
    ``(best_email_str, best_phone_str)`` — either may be ``""``.
    """
    base          = target["website"].rstrip("/")
    contact_paths = cfg.get("contact_paths", ["/contact", "/about"])
    pw_timeout    = cfg.get("playwright_timeout", 8000)
    emails: list[str] = []
    phones: list[str] = []

    urls_to_visit = [base] + [base + p for p in contact_paths[:2]]

    for i, url in enumerate(urls_to_visit):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=pw_timeout)
            if i == 0:
                dismiss_cookie_banner(page, cfg)
            content = page.content()
            emails.extend(extract_emails_full(content))
            phones.extend(extract_phones(content))
            if any(score_email(e, cfg) <= 2 for e in emails):
                break
        except Exception:
            continue
        _rate_limit(cfg)

    return best_email(emails, cfg), phones[0] if phones else ""
