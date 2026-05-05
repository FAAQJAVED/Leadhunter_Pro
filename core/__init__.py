"""
core — Internal modules for LeadHunter Pro Phase 2 (contact enrichment).

Public surface (imported by enricher.py and tests):
  email_utils   — extraction, decoding, scoring
  http_utils    — fetch_url, enrich_one_http
  browser_utils — launch_browser, dismiss_cookie_banner, enrich_one_browser
  storage       — checkpoint, xlsx/csv output
  controls      — State, ControlListener, AutoSaver, helpers
  relevance     — query-keyword lead quality scoring
"""

from core.email_utils import (
    extract_emails_raw,
    extract_emails_full,
    decode_cloudflare_email,
    extract_phones,
    score_email,
    best_email,
)
from core.http_utils import fetch_url, enrich_one_http
from core.browser_utils import launch_browser, dismiss_cookie_banner, enrich_one_browser
from core.storage import (
    save_checkpoint,
    load_checkpoint,
    save_output,
    load_existing_output,
    get_output_path,
)
from core.controls import (
    State,
    ControlListener,
    AutoSaver,
    check_cmd_file,
    wait_if_paused,
    should_stop,
    has_internet,
    wait_for_internet,
    check_disk,
)
from core.relevance import score_relevance

__all__ = [
    # email_utils
    "extract_emails_raw",
    "extract_emails_full",
    "decode_cloudflare_email",
    "extract_phones",
    "score_email",
    "best_email",
    # http_utils
    "fetch_url",
    "enrich_one_http",
    # browser_utils
    "launch_browser",
    "dismiss_cookie_banner",
    "enrich_one_browser",
    # storage
    "save_checkpoint",
    "load_checkpoint",
    "save_output",
    "load_existing_output",
    "get_output_path",
    # controls
    "State",
    "ControlListener",
    "AutoSaver",
    "check_cmd_file",
    "wait_if_paused",
    "should_stop",
    "has_internet",
    "wait_for_internet",
    "check_disk",
    # relevance
    "score_relevance",
]
