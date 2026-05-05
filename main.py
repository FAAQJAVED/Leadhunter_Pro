"""
LeadHunter Pro — Phase 1: Multi-Engine Search Scraper
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import subprocess
import sys
import time
from datetime import datetime

try:
    import winsound
    def _beep(freq: int, dur: int) -> None:
        try:
            winsound.Beep(freq, dur)
        except Exception:
            pass
except ImportError:
    def _beep(freq: int, dur: int) -> None:
        print("\a", end="", flush=True)

import httpx
from tqdm import tqdm

from config import (
    BEEP_COMPLETE,
    BEEP_ERROR,
    BING_PROXY,
    DELAY_BETWEEN_ENGINES,
    DELAY_BETWEEN_PAGES,
    DELAY_BETWEEN_QUERIES,
    ENGINES_PRIORITY,
    PAGES_PER_QUERY,
)
from core.controls import ControlListener, State, interruptible_sleep
from engines import ENGINE_MAP
from pipeline.data_cleaner import DataCleaner
from pipeline.http_client import HttpClient
from pipeline.logger_setup import setup_logging
from pipeline.output_writer import OutputWriter
from pipeline.query_manager import CheckpointStore, QueryManager

# Accept-Language: en-GB matches HttpClient session headers
_BASE_HDRS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1", "Upgrade-Insecure-Requests": "1",
}
_DDG_WARMUP_HDRS   = {**_BASE_HDRS, "Referer": "https://duckduckgo.com/",
                      "Origin": "https://duckduckgo.com"}
_YAHOO_WARMUP_HDRS = {**_BASE_HDRS, "Referer": "https://search.yahoo.com/"}


def _do_engine_warmup(engine_name: str, shared_client: HttpClient,
                      logger: logging.Logger) -> bool:
    """
    Perform session warmup for the given engine.

    Returns True if the engine should proceed, False if it should be skipped
    (e.g. Yahoo IP rate-limit is active and both warmup attempts failed).
    """
    if engine_name == "duckduckgo":
        logger.info("[warmup] DDG — fetching duckduckgo.com for fresh session...")
        try:
            resp = httpx.get(
                "https://duckduckgo.com/", headers=_DDG_WARMUP_HDRS,
                timeout=httpx.Timeout(10.0, connect=10, read=20),
                follow_redirects=True,
            )
            shared_client.session.cookies.update(dict(resp.cookies))
            shared_client.set_headers({
                "Referer": "https://duckduckgo.com/",
                "Origin":  "https://duckduckgo.com",
            })
            logger.info("[warmup] DDG HTTP %d (%d cookies)", resp.status_code,
                        len(dict(resp.cookies)))
        except Exception as exc:
            logger.warning("[warmup] DDG warmup failed: %s — proceeding", exc)
        time.sleep(random.uniform(1.0, 2.0))
        return True

    elif engine_name == "yahoo":
        logger.info("[warmup] Yahoo — two-step session warmup (yahoo.com → search.yahoo.com)...")
        yahoo_warmup_ok = False
        try:
            # Step 1: visit yahoo.com to pick up base cookies naturally
            _yahoo_home_hdrs = {**_YAHOO_WARMUP_HDRS, "Referer": ""}
            resp1 = httpx.get(
                "https://uk.yahoo.com/",
                headers={k: v for k, v in _yahoo_home_hdrs.items() if v},
                timeout=httpx.Timeout(10.0, connect=10, read=20),
                follow_redirects=True,
            )
            shared_client.session.cookies.update(dict(resp1.cookies))
            logger.info("[warmup] Yahoo home HTTP %d (%d cookies)", resp1.status_code,
                        len(dict(resp1.cookies)))
            time.sleep(random.uniform(1.5, 2.5))

            # Step 2: hit search.yahoo.com with the cookies from step 1
            resp = httpx.get(
                "https://search.yahoo.com/",
                headers=_YAHOO_WARMUP_HDRS,
                cookies=dict(resp1.cookies),
                timeout=httpx.Timeout(10.0, connect=10, read=20),
                follow_redirects=True,
            )
            shared_client.session.cookies.update(dict(resp.cookies))
            shared_client.set_headers({"Referer": "https://search.yahoo.com/"})
            logger.info("[warmup] Yahoo search HTTP %d (%d cookies)", resp.status_code,
                        len(dict(resp.cookies)))

            if resp.status_code == 500:
                # First 500: wait 90–150 seconds (Yahoo IP rate-limits typically
                # reset within 2 minutes; 20-35s was too short)
                wait = random.uniform(90, 150)
                logger.warning(
                    "[warmup] Yahoo HTTP 500 — IP rate-limited. "
                    "Waiting %.0fs for cooldown before retry...", wait
                )
                time.sleep(wait)
                resp2 = httpx.get(
                    "https://search.yahoo.com/",
                    headers=_YAHOO_WARMUP_HDRS,
                    cookies=dict(resp.cookies),
                    timeout=httpx.Timeout(15.0, connect=10, read=25),
                    follow_redirects=True,
                )
                shared_client.session.cookies.update(dict(resp2.cookies))
                logger.info("[warmup] Yahoo retry HTTP %d (%d cookies)",
                            resp2.status_code, len(dict(resp2.cookies)))

                if resp2.status_code == 500:
                    # Both attempts failed — Yahoo has hard-blocked this IP.
                    # Skip Yahoo for this run rather than wasting time on 500s.
                    logger.warning(
                        "[warmup] Yahoo blocked after 2 attempts "
                        "(IP rate-limit active). Skipping Yahoo this run. "
                        "Wait 10+ minutes then try: python main.py --yahoo --fresh"
                    )
                    return False  # signal to caller: skip this engine
                else:
                    yahoo_warmup_ok = True
            else:
                yahoo_warmup_ok = True

        except Exception as exc:
            logger.warning("[warmup] Yahoo warmup failed: %s — proceeding anyway", exc)
            yahoo_warmup_ok = False

        if yahoo_warmup_ok:
            time.sleep(random.uniform(2.0, 3.0))
            return True
        else:
            time.sleep(random.uniform(3.0, 5.0))
            return True  # warmup failed but engine may still work — let it try

    # Mojeek, Bing, and any future engines need no warmup
    return True


def parse_args() -> argparse.Namespace:
    """Parses command line arguments."""
    p = argparse.ArgumentParser(prog="main")
    p.add_argument("--version", action="version", version="LeadHunter Pro 1.1.0")
    p.add_argument("--query",   help="Single search query")
    p.add_argument("--queries", default="queries.txt")
    p.add_argument("--csv",     help="Path to CSV file of queries")
    p.add_argument("--column",  default=0)
    p.add_argument("--pages",   type=int, default=PAGES_PER_QUERY)
    p.add_argument("--engines", nargs="+", default=None, metavar="ENGINE")
    p.add_argument("--mojeek", action="store_true")
    p.add_argument("--ddg",    action="store_true")
    p.add_argument("--yahoo",  action="store_true")
    p.add_argument("--bing",   action="store_true")
    p.add_argument("--resume",  action="store_true")
    p.add_argument("--fresh",   action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Print the run plan without making any requests")
    args = p.parse_args()

    shorthand = []
    if args.mojeek:
        shorthand.append("mojeek")
    if args.ddg:
        shorthand.append("duckduckgo")
    if args.yahoo:
        shorthand.append("yahoo")
    if args.bing:
        shorthand.append("bing")
    if shorthand:
        args.engines = shorthand
    elif args.engines is None:
        args.engines = list(ENGINES_PRIORITY)

    _ALIASES = {"ddg": "duckduckgo", "duck": "duckduckgo"}
    _VALID   = {"mojeek", "yahoo", "duckduckgo", "bing", "ddg", "duck", "all"}
    resolved = []
    for name in args.engines:
        if name == "all":
            resolved = list(ENGINES_PRIORITY)
            break
        if name not in _VALID:
            p.error(f"Unknown engine {name!r}.")
        resolved.append(_ALIASES.get(name, name))
    seen: set = set()
    args.engines = [e for e in resolved if not (e in seen or seen.add(e))]

    if "bing" in args.engines and not BING_PROXY:
        print("  ⚠  BING_PROXY not set — Bing will auto-skip on geo-wrong page 1.\n")

    return args


def _launch_enricher(csv_path: str, logger: logging.Logger) -> None:
    """Launches the enrichment phase."""
    try:
        import enricher
        sys.argv = ["enricher", "--input", csv_path]
        enricher.main()
    except Exception as exc:
        logger.error("Could not import enricher.py: %s", exc)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "enricher.py")
        subprocess.run([sys.executable, script, "--input", csv_path])


def _prompt_phase2(csv_path: str, record_count: int, logger: logging.Logger) -> None:
    """Prompts the user to proceed to Phase 2."""
    print()
    print("═" * 58)
    print(f"  Phase 1 complete  ─  {record_count} leads collected")
    print()
    print("  Proceed to Phase 2?")
    print("  [Y] Yes  — extract emails, phones & score lead quality")
    print("  [N] No   — save CSV and exit")
    print("  [V] View — open output folder first, then decide")
    print("═" * 58)

    while True:
        try:
            ans = input("  Choice [Y/N/V]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            break

        if ans == "Y":
            _launch_enricher(csv_path, logger)
            break
        elif ans == "N":
            print(f"\n  Saved. Run enricher.py --input {csv_path} when ready.\n")
            break
        elif ans == "V":
            folder = os.path.dirname(os.path.abspath(csv_path))
            if sys.platform == "win32":
                subprocess.Popen(f'explorer "{folder}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        else:
            print("  Please enter Y, N, or V.")


def _console_line(engine: str, query: str, page: int, found: int, total: int) -> str:
    """Formats a console status line."""
    ts = datetime.now().strftime("%H:%M:%S")
    return (f"[{ts}] {engine.capitalize():<12} | "
            f'"{query[:35]}" | Page {page} | '
            f"+{found} results (Total: {total})")


def _audio_complete() -> None:
    _beep(*BEEP_COMPLETE)


def _audio_error() -> None:
    for _ in range(3):
        _beep(*BEEP_ERROR)
        time.sleep(0.15)


def build_query_manager(args: argparse.Namespace, checkpoint: CheckpointStore) -> QueryManager:
    """Builds and initializes the QueryManager."""
    qm = QueryManager(checkpoint)
    loaded_any = False
    if os.path.exists(args.queries):
        qm.load_from_file(args.queries)
        loaded_any = True
    elif args.queries != "queries.txt":
        print(f"  ⚠  Query file not found: {args.queries}")
    if args.csv:
        col = args.column
        try:
            col = int(col)
        except (ValueError, TypeError):
            pass
        qm.load_from_csv(args.csv, column=col)
        loaded_any = True
    if args.query:
        qm.add_single(args.query)
        loaded_any = True
    if not loaded_any:
        print("\n  ERROR: No queries provided.\n")
        sys.exit(1)
    return qm


def main() -> None:
    args   = parse_args()
    level  = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logging(level)
    logger.info("=" * 60)
    logger.info("LeadHunter Pro — Phase 1 starting")
    logger.info("Engines: %s | Pages/query: %d", args.engines, args.pages)
    logger.info("Controls: P=pause  R=resume  Q=quit  S=status  W=handoff")

    # Initialise shared state and keyboard listener
    state = State()
    ctx   = {'found': 0, 'done': 0}
    ControlListener(state, ctx)

    checkpoint = CheckpointStore()
    has_checkpoint = checkpoint.load()
    if has_checkpoint and not args.fresh:
        if args.resume:
            logger.info("Resuming from checkpoint (--resume flag)")
        else:
            resume = checkpoint.ask_resume()
            if not resume:
                checkpoint.reset()
                logger.info("Starting fresh — checkpoint cleared")
    elif args.fresh:
        checkpoint.reset()

    qm = build_query_manager(args, checkpoint)
    pending = qm.pending()
    if not pending:
        print("\n  ✅ All queries already completed. Use --fresh to start over.\n")
        sys.exit(0)
    logger.info("Queries: %d total, %d pending", qm.total(), len(pending))

    if args.dry_run:
        print("\n  DRY RUN — no requests will be made")
        print(f"  Engines  : {', '.join(args.engines)}")
        print(f"  Queries  : {qm.total()} total, {len(pending)} pending")
        print(f"  Pages    : {args.pages} per query per engine")
        print(f"  Est. ops : {len(pending) * len(args.engines)} engine-query combinations\n")
        return

    client  = HttpClient()
    cleaner = DataCleaner()
    cleaner.load_seen_domains(checkpoint.collected_domains)
    writer  = OutputWriter(engines=args.engines)

    total_ops = len(pending) * len(args.engines)
    pbar = tqdm(
        total=total_ops,
        unit="engine-query",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        colour="cyan",
        dynamic_ncols=True,
    )

    skipped_engines: dict[str, bool] = {}
    # Per-engine statistics counters
    engine_stats: dict[str, dict] = {e: {'found': 0, 'pages': 0} for e in args.engines}
    csv_path = ""

    try:
        for engine_name in args.engines:
            if skipped_engines.get(engine_name) or state.stop:
                pbar.update(len(pending))
                continue

            should_run = _do_engine_warmup(engine_name, client, logger)
            if not should_run:
                logger.warning("[%s] Warmup returned skip signal — excluding engine this run",
                               engine_name)
                skipped_engines[engine_name] = True
                pbar.update(len(pending))
                continue

            EngineCls = ENGINE_MAP[engine_name]
            engine = (
                EngineCls(client=client, delay_pages=DELAY_BETWEEN_PAGES,
                          proxy_url=BING_PROXY)
                if engine_name == "bing"
                else EngineCls(client=client, delay_pages=DELAY_BETWEEN_PAGES)
            )

            for q_idx, query in enumerate(pending):
                if state.stop:
                    break
                    
                pbar.set_description(f"{engine_name.capitalize()[:6]} | {query[:30]}")

                try:
                    raw_results = engine.search(query, pages=args.pages)
                    engine_stats[engine_name]['pages'] += args.pages
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.exception("Engine %s crashed on query %r: %s",
                                     engine_name, query, exc)
                    raw_results = []

                new_records: list = []
                for r in raw_results:
                    rec = cleaner.process(r, search_query=query,
                                         search_engine=engine_name)
                    if rec:
                        writer.add(rec)
                        new_records.append(rec)
                        checkpoint.add_domain(rec.domain)

                checkpoint.on_records_added(len(new_records))
                qm.mark_done(query)
                
                # Update live status counters
                ctx['found'] = writer.count()
                ctx['done'] += 1
                engine_stats[engine_name]['found'] += len(new_records)

                line = _console_line(engine_name, query, args.pages,
                                     len(new_records), writer.count())
                tqdm.write(line)
                logger.debug(line)
                pbar.update(1)

                if engine.is_banned:
                    logger.warning("[%s] Engine banned — skipping remaining queries",
                                   engine_name)
                    skipped_engines[engine_name] = True
                    pbar.update(len(pending) - q_idx - 1)
                    break

                if q_idx < len(pending) - 1 and not state.stop:
                    wait = random.uniform(*DELAY_BETWEEN_QUERIES)
                    logger.debug("Query delay: %.1fs", wait)
                    # Interruptible sleep (respects P/Q/R controls)
                    interruptible_sleep(state, wait)

            if state.stop:
                break

            remaining = [e for e in args.engines
                         if e != engine_name and not skipped_engines.get(e)]
            if remaining:
                wait = random.uniform(*DELAY_BETWEEN_ENGINES)
                logger.info("Switching engine in %.0fs...", wait)
                # Interruptible sleep (respects P/Q/R controls)
                interruptible_sleep(state, wait)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user — saving progress...")
        _audio_error()
    except Exception as exc:
        logger.exception("CRITICAL ERROR: %s", exc)
        _audio_error()
    finally:
        pbar.close()
        client.close()
        checkpoint.save()

    if writer.count() == 0:
        logger.warning("No records collected — no output files written.")
        _audio_error()
        return

    try:
        csv_path, xlsx_path = writer.write_all()
    except Exception as exc:
        logger.exception("Output write failed: %s", exc)
        _audio_error()
        return

    elapsed_s = pbar.format_dict.get("elapsed", 0) or 0
    h, rem    = divmod(int(elapsed_s), 3600)
    m, s      = divmod(rem, 60)

    print()
    print("=" * 60)
    print("  ✅  PHASE 1 COMPLETE")
    print(f"  Total leads found  : {writer.count():,}")
    print(f"  Unique domains     : {len({r.domain for r in writer._records}):,}")
    print(f"  Flagged/excluded   : {sum(1 for r in writer._records if r.flagged):,}")
    print(f"  Time elapsed       : {h:02d}:{m:02d}:{s:02d}")
    
    # Per-engine summary table
    print("-" * 60)
    print(f"  {'Engine':<15} | {'Leads':<10} | {'Pages':<10}")
    print("-" * 60)
    for eng, stats in engine_stats.items():
        print(f"  {eng.capitalize():<15} | {stats['found']:<10} | {stats['pages']:<10}")
    print("-" * 60)
    
    print(f"  CSV saved to       : {csv_path}")
    print(f"  Excel saved to     : {xlsx_path}")
    print("=" * 60)
    _audio_complete()

    if state.handoff:
        _launch_enricher(csv_path, logger)
    else:
        _prompt_phase2(csv_path, writer.count(), logger)


if __name__ == "__main__":
    main()
