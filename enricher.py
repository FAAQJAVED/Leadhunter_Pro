"""
LeadHunter Pro — Phase 2: Email & Phone Enrichment

Reads a CSV of company websites (produced by Phase 1 or any other source)
and scrapes each site for contact email addresses AND phone numbers using
two sequential passes, then scores lead quality using query-keyword matching.

  Pass 1 — Concurrent HTTP GET  (ThreadPoolExecutor, configurable workers)
  Pass 2 — Playwright           (headless Chromium fallback for JS-rendered sites)
  Phase 3 — Relevance scoring (HOT/WARM/COLD/NOISE per lead)

Results are written to an Excel workbook (+ CSV backup) with a Run Stats sheet.
Progress is checkpointed so any interrupted run can be resumed.
Auto-saves every N sites AND every 60 seconds in a background thread.

Column detection is fully automatic — no need to rename CSV headers.
Input file detection is automatic — no need to rename your file.

Key behaviours:
  - Directory-flagged rows are filtered out before enrichment begins.
  - Pass 1 runs concurrently via ThreadPoolExecutor (enricher_workers).
  - Generic email keywords are industry-agnostic.
  - Emails are deduplicated before best_email() selection.

Usage
-----
  python enricher.py                          # auto-detects CSV in current dir
  python enricher.py --input my_leads.csv
  python enricher.py --input leads.csv --config my_config.yaml
  python enricher.py --fresh                  # clear checkpoint and restart
  python enricher.py --output results.xlsx

Runtime controls (while running)
---------------------------------
  P  — pause / resume
  R  — resume
  Q  — quit (saves progress first)
  S  — print current status
  W  — handoff (same as Q here — saves and exits)
  Windows: single-key (no Enter needed)
  Mac/Linux: type the letter then press Enter
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

try:
    from tqdm import tqdm as _TqdmClass
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    class _TqdmClass:                      # type: ignore[no-redef]
        def __init__(self, *a, **kw) -> None:
            self.total = kw.get("total", 0)
            self.n     = 0
        def update(self, n: int = 1) -> None:     self.n += n
        def set_postfix(self, **kw) -> None:      pass
        def write(self, s: str) -> None:          print(s, flush=True)
        def close(self) -> None:                  pass
        def __enter__(self):                      return self
        def __exit__(self, *a) -> None:           pass

from core._log import elapsed, log, set_active_bar, set_start_time
from core.controls import (
    AutoSaver,
    ControlListener,
    State,
    check_cmd_file,
    check_disk,
    should_stop,
    wait_for_internet,
    wait_if_paused,
)
from core.http_utils import enrich_one_http, extract_company_name, fetch_url
from core.relevance import score_relevance
from core.storage import (
    get_output_path,
    load_checkpoint,
    load_existing_output,
    save_checkpoint,
    save_output,
)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "input_file":            "",
    "output_file":           "",
    "checkpoint_file":       "enrich_checkpoint.json",
    "command_file":          "command.txt",
    "output_format":         "xlsx",
    "http_timeout":          [4, 6],
    "playwright_timeout":    8000,
    "browser_restart_every": 150,
    "stop_at":               "",        # "" = disabled; set to "HH:MM" to auto-stop
    "autosave_interval":     60,
    # Concurrent worker count for Pass 1 HTTP enrichment
    "enricher_workers":      5,
    "rate_limit": {
        "min_seconds": 0.1,
        "max_seconds": 0.5,
    },
    "user_agents": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:109.0) Gecko/20100101 Firefox/120.0",
    ],
    "contact_paths": [
        "/contact", "/contact-us", "/about", "/about-us",
    ],
    "locale": "en-US",
    "columns": {
        "company_name": "",
        "website":      "",
        "email":        "Email",
        "phone":        "Phone",
        "category":     "",
    },
    "skip_email_keywords": [
        "noreply", "no-reply", "donotreply", "privacy", "dataprotection",
        "data-protection", "gdpr", "unsubscribe", "postmaster", "webmaster",
        "bounce", "complaints", "legal", "abuse", "spam", "newsletter",
    ],
    # Only universally generic prefixes are included here — tool is industry-agnostic
    "generic_email_keywords": [
        "info", "admin", "hello", "contact", "enquiries", "enquiry", "office",
        "mail", "email", "team", "support", "help", "sales",
        "accounts", "finance", "general", "service", "post",
    ],
    # Expanded junk domains — consistent with _PLACEHOLDER_DOMAINS in core/email_utils.py
    "junk_email_domains": [
        "sentry.io", "wixpress.com", "example.com", "schema.org", "w3.org",
        "googleapis.com", "cloudflare.com", "jquery.com",
        "placeholder.com", "domain.com", "email.com", "doe.com", "test.com",
        "mailinator.com", "yopmail.com", "tempmail.com", "trashmail.com",
    ],
    "cookie_selectors": [
        'button:has-text("Accept all")',
        'button:has-text("Accept cookies")',
        'button:has-text("Accept")',
        'button:has-text("I Accept")',
        'button:has-text("Allow all")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        '[id*="accept"]',
        '[aria-label*="Accept"]',
    ],
}


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML merged on top of hard-coded defaults."""
    cfg = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        for key, val in user_cfg.items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(val)
            else:
                cfg[key] = val
    return cfg


# ---------------------------------------------------------------------------
# Input loading / column detection
# ---------------------------------------------------------------------------

def _detect_column(headers: list[str], *keywords: str) -> str | None:
    """Find the first header that contains any of the given keywords (case-insensitive)."""
    for h in headers:
        h_lower = h.lower()
        if any(kw in h_lower for kw in keywords):
            return h
    return None


def find_input_file() -> str | None:
    """
    Auto-detect the input CSV from the current working directory OR outputs/.

    Search order:
      1. Current directory (``*.csv``)
      2. ``outputs/`` subdirectory (where Phase 1 writes its CSVs)

    Selection:
      - Exactly one CSV total → use it automatically.
      - Multiple CSVs → sort by modification time, show newest first,
        and let user confirm or choose a different one.
      - None found → return ``None``.
    """
    csv_files: list = sorted(Path(".").glob("*.csv"))

    # Also search outputs/ — Phase 1 always writes there
    outputs_dir = Path("outputs")
    if outputs_dir.is_dir():
        csv_files += sorted(outputs_dir.glob("*.csv"))

    if not csv_files:
        return None

    # De-duplicate resolved paths
    seen: set = set()
    unique: list = []
    for f in csv_files:
        resolved = str(f.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)
    csv_files = unique

    if len(csv_files) == 1:
        return str(csv_files[0])

    # Sort newest-first by modification time
    csv_files_sorted = sorted(csv_files, key=lambda f: f.stat().st_mtime, reverse=True)
    newest = csv_files_sorted[0]

    print(f"\nMultiple CSV files found. Newest: {newest.name}")
    print("  Press Enter to use it, or pick another:\n")
    for i, f in enumerate(csv_files_sorted, 1):
        marker = " ← newest" if i == 1 else ""
        print(f"  {i}. {f}{marker}")
    print()

    while True:
        try:
            raw = input("  Enter number (or press Enter for newest): ").strip()
            if not raw:
                return str(newest)
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(csv_files_sorted):
                    return str(csv_files_sorted[idx])
            elif os.path.exists(raw):
                return raw
            print("  Invalid choice — try again.")
        except (EOFError, KeyboardInterrupt):
            return str(newest)


def _detect_engines_from_csv(filepath: str) -> str:
    """
    Read unique engine names from the 'Search Engine' column of the input CSV
    and return them joined with underscore for use in the output filename.

    E.g. a CSV produced by --mojeek returns "mojeek", one produced by
    --mojeek --ddg returns "ddg_mojeek" (alphabetically sorted).

    Returns "" if the column is absent or the file cannot be read.
    """
    try:
        with open(filepath, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return ""
        headers = list(rows[0].keys())
        col = _detect_column(headers, "search_engine", "engine", "source")
        if not col:
            return ""
        engines = {r[col].strip().lower() for r in rows if r.get(col, "").strip()}
        _SHORT = {"duckduckgo": "ddg"}
        short  = "_".join(_SHORT.get(e, e) for e in sorted(engines))
        return short
    except Exception:
        return ""


def load_input(cfg: dict) -> list[dict]:
    """
    Load and validate the input CSV with fully automatic column detection.

    Rows where flagged == 'YES' and flag_reason == 'directory' are
    skipped before enrichment. These are definitively not company sites and
    would waste Pass 1 and Pass 2 time. The skip count is logged at startup.

    Detection priority
    ------------------
    Website  (REQUIRED) : website · url · domain · site · web · link · homepage
    Company name (opt)  : company · name · organisation · organization · business …
    Category (opt)      : category · type · sector · industry · segment · group …
    Phone (opt)         : phone · tel · mobile · cell · number …
    """
    input_file = cfg["input_file"]
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    with open(input_file, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError("Input file is empty.")

    headers: list[str] = list(rows[0].keys())
    cols = cfg.get("columns", {})

    col_web = cols.get("website") or ""
    if not col_web or col_web not in headers:
        col_web = _detect_column(
            headers, "website", "url", "domain", "site", "web", "link", "homepage",
        )
    if not col_web:
        raise ValueError(
            f"Cannot find a website/URL column.\n"
            f"Columns found: {headers}\n"
            f"Please add a column named 'Website', 'URL', or 'Domain'."
        )

    col_name = cols.get("company_name") or ""
    if not col_name or col_name not in headers:
        col_name = _detect_column(
            headers,
            "company", "name", "organisation", "organization",
            "business", "firm", "client", "account", "brand", "title",
        )
    if not col_name:
        col_name = headers[0]
        log(f"No company-name column detected — using first column: '{col_name}'", "warn")

    col_cat = cols.get("category") or ""
    if not col_cat or col_cat not in headers:
        col_cat = _detect_column(
            headers, "category", "type", "sector", "industry",
            "segment", "group", "vertical",
        )

    col_phone_in = _detect_column(
        headers, "phone", "tel", "mobile", "cell", "number", "contact number",
    )

    col_query = _detect_column(headers, "search_query", "query", "search")

    # Detect flag columns for directory filtering
    col_flagged     = _detect_column(headers, "flagged")
    col_flag_reason = _detect_column(headers, "flag_reason")

    log(
        f"Columns → name='{col_name}'  website='{col_web}'"
        + (f"  category='{col_cat}'" if col_cat else "")
        + (f"  phone_in='{col_phone_in}'" if col_phone_in else "")
        + (f"  search_query='{col_query}'" if col_query else "")
    )

    targets = []
    skipped_directory = 0

    for row in rows:
        url = row.get(col_web, "").strip()
        if not url:
            continue

        # Skip directory-flagged rows — aggregator/portal sites that won't yield direct contacts
        if col_flagged and col_flag_reason:
            if (row.get(col_flagged, "").strip().upper() == "YES"
                    and row.get(col_flag_reason, "").strip().lower() == "directory"):
                skipped_directory += 1
                continue

        targets.append({
            "key":          row[col_name].strip().lower(),
            "name":         row[col_name].strip(),
            "website":      url,
            "phone":        row.get(col_phone_in, "").strip() if col_phone_in else "",
            "category":     row.get(col_cat,      "").strip() if col_cat      else "",
            "search_query": row.get(col_query,     "").strip() if col_query    else "",
        })

    if skipped_directory:
        log(f"Skipped {skipped_directory} directory-flagged rows from input", "warn")

    return targets


# ---------------------------------------------------------------------------
# Pass 1 — Concurrent HTTP enrichment
# ---------------------------------------------------------------------------

def run_pass1(
    targets:  list[dict],
    done:     set[str],
    found:    dict,
    out_file: str,
    state:    State,
    ctx:      dict,
    cfg:      dict,
) -> list[dict]:
    """
    Execute Pass 1: concurrent HTTP enrichment for all targets not yet in found.

    Uses ThreadPoolExecutor with cfg['enricher_workers'] (default 5)
    so multiple sites are fetched in parallel. A threading.Lock guards all
    writes to the shared found dict and checkpoint saves.

    Each worker:
      1. Checks state.stop — returns immediately if quitting.
      2. Fetches homepage HTML for relevance scoring.
      3. Calls enrich_one_http (homepage + contact paths).
      4. Deduplicates emails before best_email() selection.

    Returns targets that yielded no contacts (queued for Playwright Pass 2).
    """
    todo     = [t for t in targets if t["key"] not in found]
    workers  = cfg.get("enricher_workers", 5)
    stop_at  = cfg.get("stop_at", "")
    ckpt     = cfg["checkpoint_file"]
    cmd_file = cfg["command_file"]
    lock     = threading.Lock()

    log(
        f"Pass 1 — {len(todo)} sites → concurrent HTTP "
        f"({workers} workers, homepage + {len(cfg.get('contact_paths', []))} contact paths)"
    )

    if not todo:
        log("Pass 1: nothing to process")
        return []

    needs_pw:    list[dict] = []
    pass1_found: int        = 0
    save_counter: int       = 0

    bar = _TqdmClass(
        total=len(todo),
        desc="  Pass 1 (HTTP)   ",
        unit="site",
        dynamic_ncols=True,
        colour="cyan" if TQDM_AVAILABLE else None,
    )
    set_active_bar(bar)

    def _worker(target: dict) -> tuple[dict, str, str, str, dict]:
        """
        Enrich one site via HTTP and optionally score relevance.

        Returns (target, email, phone, scraped_name, relevance_data).
        On stop returns (target, "", "", "", {}).
        """
        if should_stop(state, stop_at):
            return target, "", "", "", {}

        base = target["website"].rstrip("/")

        try:
            email, phone, scraped_name = enrich_one_http(target, cfg)
        except Exception as exc:
            log(f"HTTP error [{target.get('name', base)}]: {exc}", "warn")
            email, phone, scraped_name = "", "", ""

        # Score relevance with one homepage fetch (only when query available)
        relevance_data: dict = {}
        if target.get("search_query"):
            try:
                homepage_html = fetch_url(base, cfg)
                if homepage_html:
                    relevance_data = score_relevance(homepage_html, target["search_query"])
            except Exception:
                pass

        return target, email, phone, scraped_name, relevance_data

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_worker, t): t for t in todo}

            for future in as_completed(futures):
                # Control checks happen in the result-collection loop (main thread)
                check_cmd_file(state, cmd_file, ckpt)
                if should_stop(state, stop_at):
                    break
                wait_if_paused(state, ctx, cmd_file, ckpt)
                if should_stop(state, stop_at):
                    break

                try:
                    target, email, phone, scraped_name, relevance_data = future.result()
                except Exception as exc:
                    log(f"Worker exception: {exc}", "warn")
                    bar.update(1)
                    continue

                with lock:
                    done.add(target["key"])
                    ctx["done"] = len(done)

                    if email or phone:
                        record = {
                            "name":     scraped_name or target["name"],
                            "website":  target["website"],
                            "email":    email,
                            "phone":    phone or target.get("phone", ""),
                            "category": target["category"],
                        }
                        if relevance_data:
                            record["lead_quality"]      = relevance_data["lead_quality"]
                            record["keyword_match_pct"] = relevance_data["keyword_match_pct"]
                        found[target["key"]] = record
                        pass1_found += 1
                        ctx["found"] = pass1_found
                    elif target.get("phone"):
                        record = {
                            "name":     scraped_name or target["name"],
                            "website":  target["website"],
                            "email":    "",
                            "phone":    target["phone"],
                            "category": target["category"],
                        }
                        if relevance_data:
                            record["lead_quality"]      = relevance_data["lead_quality"]
                            record["keyword_match_pct"] = relevance_data["keyword_match_pct"]
                        found[target["key"]] = record
                        pass1_found += 1
                        ctx["found"] = pass1_found
                    else:
                        needs_pw.append(target)

                    save_counter += 1
                    if save_counter % 10 == 0:
                        save_checkpoint(done, found, ckpt)
                        save_output(found, out_file, cfg)
                        check_disk()

                bar.update(1)

    finally:
        set_active_bar(None)
        bar.close()

    print()
    save_checkpoint(done, found, ckpt)
    save_output(found, out_file, cfg)
    log(f"Pass 1 done — {pass1_found} contacts found via HTTP ({workers} workers)", "good")
    return needs_pw


# ---------------------------------------------------------------------------
# Pass 2 — Sequential Playwright enrichment
# ---------------------------------------------------------------------------

def run_pass2(
    needs_pw: list[dict],
    done:     set[str],
    found:    dict,
    out_file: str,
    state:    State,
    ctx:      dict,
    cfg:      dict,
    stats:    dict,
) -> None:
    """
    Execute Pass 2: Playwright-based enrichment for JS-heavy sites.

    Uses ``sync_playwright().__enter__()`` — never ``with sync_playwright()``.
    This avoids a Windows/Python 3.12 ContextVar incompatibility.

    The browser is restarted every ``browser_restart_every`` sites to
    prevent memory accumulation on large runs.

    Playwright is intentionally sequential — it is not safe to share a single
    browser instance across threads, and launching per-worker instances would
    consume too much memory. Sites that need Playwright are typically < 20%
    of the total; sequential is acceptable here.
    """
    todo          = [t for t in needs_pw if t["key"] not in found]
    stop_at       = cfg.get("stop_at", "")
    ckpt          = cfg["checkpoint_file"]
    cmd_file      = cfg["command_file"]
    restart_every = cfg.get("browser_restart_every", 150)

    log(f"Pass 2 — {len(todo)} sites → Playwright headless browser")

    if not todo:
        log("Pass 2: nothing to process")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log(
            "playwright not installed — "
            "run: pip install playwright && python -m playwright install chromium",
            "error",
        )
        return

    from core.browser_utils import enrich_one_browser, launch_browser

    pass2_found: int = 0
    pw_count:    int = 0

    bar = _TqdmClass(
        total=len(todo),
        desc="  Pass 2 (Browser)",
        unit="site",
        dynamic_ncols=True,
        colour="green" if TQDM_AVAILABLE else None,
    )
    set_active_bar(bar)

    # CRITICAL: use __enter__() / __exit__() — never `with sync_playwright()`
    _pw_ctx = sync_playwright()
    pw      = _pw_ctx.__enter__()
    try:
        browser, page = launch_browser(pw, cfg)

        for count, target in enumerate(todo, 1):
            check_cmd_file(state, cmd_file, ckpt)
            if should_stop(state, stop_at):
                break
            wait_if_paused(state, ctx, cmd_file, ckpt)
            if should_stop(state, stop_at):
                break

            if pw_count > 0 and pw_count % restart_every == 0:
                log(f"Restarting browser after {pw_count} sites …", "dim")
                try:
                    browser.close()
                except Exception:
                    pass
                time.sleep(2)
                browser, page = launch_browser(pw, cfg)

            email, phone = enrich_one_browser(page, target, cfg)
            done.add(target["key"])
            pw_count += 1
            ctx["done"] = len(done)

            if email or phone:
                try:
                    page_html = page.content()
                except Exception:
                    page_html = ""

                # Scrape real company name from the rendered page, same as Pass 1
                scraped_name = extract_company_name(page_html, fallback="") if page_html else ""

                relevance_data: dict = {}
                if page_html and target.get("search_query"):
                    try:
                        relevance_data = score_relevance(page_html, target["search_query"])
                    except Exception:
                        pass

                record = {
                    "name":     scraped_name or target["name"],
                    "website":  target["website"],
                    "email":    email,
                    "phone":    phone or target.get("phone", ""),
                    "category": target["category"],
                }
                if relevance_data:
                    record["lead_quality"]      = relevance_data["lead_quality"]
                    record["keyword_match_pct"] = relevance_data["keyword_match_pct"]

                found[target["key"]]  = record
                pass2_found          += 1
                ctx["found"]          = pass2_found
                stats["pass2_found"]  = pass2_found

            if count % 10 == 0:
                if not check_disk():
                    break
                save_checkpoint(done, found, ckpt)
                save_output(found, out_file, cfg, stats)
                wait_for_internet(state)
                if should_stop(state, stop_at):
                    break

            rem   = len(todo) - count
            eta   = int(rem * 3 / 60)
            eta_s = f"~{eta // 60}h{eta % 60:02d}m" if eta >= 60 else f"~{eta}m"
            pct   = round(pass2_found / count * 100)
            bar.set_postfix(found=pass2_found, hit=f"{pct}%", eta=eta_s)
            bar.update(1)
            time.sleep(0.1)

        try:
            browser.close()
        except Exception:
            pass

    finally:
        _pw_ctx.__exit__(None, None, None)
        set_active_bar(None)
        bar.close()

    print()
    save_checkpoint(done, found, ckpt)
    save_output(found, out_file, cfg, stats)
    log(f"Pass 2 done — {pass2_found} additional contacts found via Playwright", "good")


# ---------------------------------------------------------------------------
# Timing reference
# ---------------------------------------------------------------------------

_GLOBAL_START: float = 0.0


def _start_time_ref() -> float:
    return _GLOBAL_START


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="enricher",
        description=(
            "LeadHunter Pro — Phase 2: Email & Phone Enrichment + Lead Quality Scoring"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python enricher.py                          # auto-detect CSV in current directory
  python enricher.py --input companies.csv
  python enricher.py --input leads.csv --config my_config.yaml
  python enricher.py --fresh                  # ignore checkpoint, start over
  python enricher.py --output results.xlsx    # override output path
        """,
    )
    parser.add_argument("--version", action="version", version="LeadHunter Pro 1.1.0")
    parser.add_argument("--input",  "-i", help="Path to input CSV")
    parser.add_argument("--output", "-o", help="Path to output file")
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--fresh", "-f",
        action="store_true",
        help="Clear existing checkpoint and start from scratch",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    os_name = platform.system()
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║   LeadHunter Pro — Phase 2: Contact Enrichment       ║")
    print("║   Pass 1: Concurrent HTTP  →  Pass 2: Playwright     ║")
    print("║   Phase 3: HOT / WARM / COLD / NOISE scoring         ║")
    print("╚══════════════════════════════════════════════════════╝")
    if os_name == "Windows":
        print("  Controls: P=pause  R=resume  Q=quit  S=status  W=handoff")
    else:
        print("  Controls: type P / R / Q / S / W  then  Enter")
    if not TQDM_AVAILABLE:
        print("  Tip: pip install tqdm  for a richer progress bar")
    print()


def _print_summary(
    targets:  list[dict],
    found:    dict,
    out_file: str,
    stats:    dict,
    partial:  bool = False,
) -> None:
    total   = len(targets)
    n_email = sum(1 for v in found.values() if v.get("email"))
    n_phone = sum(1 for v in found.values() if v.get("phone"))
    n_any   = len(found)
    by_quality = Counter(
        v.get("lead_quality", "") for v in found.values() if v.get("lead_quality")
    )
    print()
    print("╔══════════════════════════════════════════════════════╗")
    log(f"  {'PARTIAL — re-run to continue' if partial else 'COMPLETE'}")
    log(f"  Companies input  : {total}")
    log(f"  Contacts found   : {n_any}  ({round(n_any / total * 100) if total else 0}%)")
    log(f"    — Emails       : {n_email}  ({round(n_email / total * 100) if total else 0}%)")
    log(f"    — Phones       : {n_phone}  ({round(n_phone / total * 100) if total else 0}%)")
    log(f"  Still missing    : {total - n_any}")
    log(f"  Pass 1 found     : {stats.get('pass1_found', 0)}")
    log(f"  Pass 2 found     : {stats.get('pass2_found', 0)}")
    if by_quality:
        log(f"  Lead quality     : HOT={by_quality.get('HOT', 0)}"
            f"  WARM={by_quality.get('WARM', 0)}"
            f"  COLD={by_quality.get('COLD', 0)}"
            f"  NOISE={by_quality.get('NOISE', 0)}")
    log(f"  Time elapsed     : {elapsed()}")
    log(f"  Output           : {os.path.abspath(out_file)}", "good")
    print("╚══════════════════════════════════════════════════════╝")
    print()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Orchestrate the two-pass email & phone enrichment + relevance scoring pipeline.

    Steps
    -----
    1. Load config (YAML merged with CLI overrides).
    2. Auto-detect or validate input CSV.
    3. Auto-detect columns (website, name, category, pre-existing phone, search_query).
    4. Filter directory-flagged rows before any enrichment begins.
    5. Resume from checkpoint / existing output if available.
    6. Pass 1 — concurrent HTTP requests with background auto-save + relevance scoring.
    7. Pass 2 — Playwright fallback (sequential) with background auto-save + relevance scoring.
    8. Write final Excel + CSV output with run statistics.
    9. Clean up checkpoint on successful full completion.
    """
    global _GLOBAL_START
    _GLOBAL_START = time.time()
    set_start_time(_GLOBAL_START)

    args = parse_args()
    cfg  = load_config(args.config)

    if args.input:
        cfg["input_file"] = args.input
    if args.output:
        cfg["output_file"] = args.output

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    _print_banner()

    if not cfg.get("input_file"):
        detected = find_input_file()
        if not detected:
            log("No input CSV found in current directory.", "error")
            log("Usage: python enricher.py --input path/to/file.csv", "info")
            return
        cfg["input_file"] = detected
        log(f"Auto-detected input: {detected}", "good")

    state = State()
    ctx:   dict = {"found": 0, "done": 0}
    stats: dict = {
        "pass1_found": 0,
        "pass2_found": 0,
        "total":       0,
        "elapsed":     "",
        "input_file":  cfg["input_file"],
    }

    ckpt = cfg["checkpoint_file"]

    if args.fresh and os.path.exists(ckpt):
        os.remove(ckpt)
        log("Checkpoint cleared — starting fresh", "warn")

    log(f"Config : {args.config}")
    log(f"Input  : {cfg['input_file']}")
    out_file = get_output_path(cfg)

    # If no explicit output_file was set, name the output after the engine(s)
    # so files are immediately recognisable (e.g. found_contacts_mojeek_20260503.xlsx)
    if not cfg.get("output_file"):
        engine_tag = _detect_engines_from_csv(cfg["input_file"])
        if engine_tag:
            ext = cfg.get("output_format", "xlsx")
            from datetime import date as _date
            cfg["output_file"] = f"found_contacts_{engine_tag}_{_date.today().strftime('%Y%m%d')}.{ext}"
            out_file = cfg["output_file"]

    log(f"Output : {out_file}  [{cfg.get('output_format', 'xlsx').upper()}]")
    log(f"Workers: {cfg.get('enricher_workers', 5)} (Pass 1 concurrent HTTP)")
    print()

    ControlListener(state, ctx)

    # Warn immediately if stop_at is already in the past
    stop_at_cfg = cfg.get("stop_at", "")
    if stop_at_cfg:
        from datetime import datetime as _dt
        now_hm = _dt.now().strftime("%H:%M")
        if now_hm >= stop_at_cfg:
            log(
                f"WARNING: stop_at is '{stop_at_cfg}' but current time is {now_hm}. "
                f"Enricher will stop immediately. "
                f"Set stop_at to a future time or leave it empty to disable.",
                "warn",
            )

    try:
        targets = load_input(cfg)
    except (FileNotFoundError, ValueError) as exc:
        log(str(exc), "error")
        return

    stats["total"] = len(targets)
    log(f"Loaded {len(targets)} rows from CSV")

    if not targets:
        log("Nothing to process.", "warn")
        return

    cats = Counter(t["category"] for t in targets if t.get("category"))
    if cats:
        log("Category breakdown:")
        for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
            log(f"  {cat:<42} {n}", "dim")
    print()

    _, found = load_checkpoint(ckpt)
    found.update(load_existing_output(out_file, cfg))
    done: set[str] = set()

    if found:
        log(f"Resuming — {len(found)} contacts already in cache", "good")
        try:
            import winsound as _ws
            _ws.Beep(600, 150)
            _ws.Beep(900, 250)
        except Exception:
            print("\a", end="", flush=True)
    else:
        log("Fresh start", "good")
        try:
            import winsound as _ws
            _ws.Beep(500, 100)
            _ws.Beep(700, 100)
            _ws.Beep(900, 200)
        except Exception:
            print("\a", end="", flush=True)

    ctx["done"] = len(found)
    autosave_interval = cfg.get("autosave_interval", 60)

    auto_saver1 = AutoSaver(found, out_file, cfg, stats, interval=autosave_interval)
    needs_pw    = run_pass1(targets, done, found, out_file, state, ctx, cfg)
    stats["pass1_found"] = len(found)
    auto_saver1.stop()

    if should_stop(state, cfg.get("stop_at", "")):
        save_checkpoint(done, found, ckpt)
        save_output(found, out_file, cfg, stats)
        _print_summary(targets, found, out_file, stats, partial=True)
        return

    print()

    auto_saver2 = AutoSaver(found, out_file, cfg, stats, interval=autosave_interval)
    run_pass2(needs_pw, done, found, out_file, state, ctx, cfg, stats)
    auto_saver2.stop()

    stats["elapsed"] = elapsed()
    save_checkpoint(done, found, ckpt)
    save_output(found, out_file, cfg, stats)

    all_done = not state.stop
    if all_done and os.path.exists(ckpt):
        os.remove(ckpt)

    try:
        import winsound as _ws
        if all_done:
            for f, d in [(600, 100), (800, 100), (1000, 100), (1200, 300)]:
                _ws.Beep(f, d)
        else:
            _ws.Beep(900, 200)
            _ws.Beep(600, 400)
    except Exception:
        print("\a", end="", flush=True)

    _print_summary(targets, found, out_file, stats, partial=not all_done)


if __name__ == "__main__":
    main()
