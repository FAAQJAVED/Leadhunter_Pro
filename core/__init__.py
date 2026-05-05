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

from core.browser_utils import dismiss_cookie_banner, enrich_one_browser, launch_browser
from core.controls import (
    AutoSaver,
    ControlListener,
    State,
    check_cmd_file,
    check_disk,
    has_internet,
    should_stop,
    wait_for_internet,
    wait_if_paused,
)
from core.email_utils import (
    best_email,
    decode_cloudflare_email,
    extract_emails_full,
    extract_emails_raw,
    extract_phones,
    score_email,
)
from core.http_utils import enrich_one_http, fetch_url
from core.relevance import score_relevance
from core.storage import (
    get_output_path,
    load_checkpoint,
    load_existing_output,
    save_checkpoint,
    save_output,
)

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
