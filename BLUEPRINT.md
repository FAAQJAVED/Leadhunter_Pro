# LeadHunter Pro — Technical Blueprint

A complete technical reference for engineers, reviewers, and anyone who needs to understand, extend, or present this system. Written so that a Python developer who has never seen this codebase can read it and confidently explain every design decision.

---

## Part 1: The Problem This Solves

### Why lead generation via search engines is non-trivial

Finding business leads from search engines sounds simple: search for "letting agents Manchester", scrape the URLs, visit each site, find the email. In practice every step has a hidden failure mode.

**Bot detection.** Search engines invest heavily in blocking automated queries. They fingerprint IP addresses, track request timing, inspect HTTP headers, check for valid session cookies, and measure how closely a client behaves like a real browser. A naive Python `requests.get()` call to Google returns a CAPTCHA within seconds. Even well-behaved scrapers receive HTTP 429 (rate-limited) or HTTP 202 (bot challenge) after a burst of requests.

**Session management.** Some engines require a valid browsing session before they will return real results. DuckDuckGo Lite returns HTTP 202 (a challenge page, not a real result page) if the client has not first loaded the DuckDuckGo homepage to establish session cookies. Yahoo returns HTTP 500 (hard block) if the client skips the landing page warmup. Getting this right requires per-engine session management, not a single shared approach.

**Rate limiting.** Sending queries too fast triggers bans. Sending them too slowly wastes time. The system uses per-engine configurable delays with random jitter to mimic human pacing.

**Geo-blocking.** Bing's search results are heavily localised. A UK server querying Bing without the correct locale headers returns German, Japanese, or French results even for English queries. Bing's own geo-override request headers must be set on every request, and results must be validated for English content before being accepted.

**HTML structure changes.** Search engines change their HTML layouts without warning. A CSS selector that worked yesterday may return zero results today. The system uses multiple fallback selectors for every engine and saves raw HTML to `debug_html/` so failures can be diagnosed without re-running.

**JavaScript-rendered pages.** Many modern company websites are React or Angular single-page applications. A plain HTTP GET returns a nearly empty HTML shell; the contact email is injected by JavaScript after the page loads. No amount of clever regex will find it. These sites require a real browser — specifically Playwright with Chromium.

**Cloudflare email obfuscation.** Cloudflare's bot-protection layer replaces email addresses in HTML with XOR-encoded hex strings rendered via JavaScript. The raw HTML contains `data-cfemail="1a727f76..."` instead of a plaintext email. Extracting these requires decoding the XOR cipher.

---

## Part 2: System Architecture

### The two-phase pipeline

**Phase 1: Search Scraping**

The scraper takes a list of search queries (e.g. "block management companies London") and runs each query against up to four search engines. Each engine returns a list of result URLs. These URLs are cleaned, deduplicated at the domain level across all engines, scored, and written to a CSV and Excel file.

Phase 1 answers: *what company websites exist that match this query?* It does not visit those websites; it only collects their URLs from search result pages.

**Why multiple engines?** Each search engine has an independent index. Mojeek's UK-biased index returns different companies than DuckDuckGo's global index. Yahoo and Bing add further coverage. Running all four and deduplicating at the domain level yields significantly more unique companies per query than any single engine.

**What deduplication achieves.** Domain-level deduplication means that if Mojeek returns `example.co.uk/` and Yahoo returns `example.co.uk/contact`, only the first encounter is kept and the second is silently dropped. This prevents one company from appearing multiple times in the output. The deduplication set is shared across all engines and persists in the checkpoint, so it is also cross-run and cross-session.

**Phase 2: Contact Enrichment**

The enricher reads the CSV produced by Phase 1 and visits each website to find a contact email and phone number. It runs in two sequential passes.

Pass 1 uses plain HTTP GET requests (the `requests` library). This is fast (~0.5 s per site) and works for the majority of company websites which serve their contact details in static HTML.

Pass 2 uses Playwright with a headless Chromium browser. Sites that returned no contact details in Pass 1 are queued for Pass 2. The browser loads the full page including executing all JavaScript, then extracts contact details from the rendered DOM. This is slower (~3–5 s per site) but catches React/Angular/Next.js sites that Pass 1 cannot reach.

**The handoff.** The user can press `W` at any time during Phase 1 to end scraping early and immediately be offered the Phase 2 prompt. This is useful for large query sets where you want to start enriching results while the scraper continues, or when you have enough leads and don't need to run all queries. When Phase 1 completes naturally, the same Phase 2 prompt is shown.

---

## Part 3: The Search Engines — How Each Works

### Mojeek (primary engine)

**Why chosen.** Mojeek is a UK-independent search engine with its own crawler and index. It has a strong bias toward UK-registered websites (`.co.uk` domains), making it the best engine for UK-focused lead generation. Its bot detection is minimal — the same IP can run hundreds of queries without triggering blocks, unlike Google, Bing, or DDG. It reliably returns 10 results per page.

**How it works.** Mojeek is queried via plain GET requests to `https://www.mojeek.com/search?q={query}&fmt=html&lang=en&hp=0&arc=none`. The `hp=0` parameter suppresses the personal search homepage; `arc=none` disables archive integrations.

**HTML structure.** Each result URL lives in an `<a class="ob" href="...">` anchor within a result list item. There are exactly 10 of these per page. The title is in an `<h2>` sibling, and the snippet is in a `<p class="s">` element.

**Selectors.** Primary: `a.ob[href]` (10 matches confirmed). Fallback: `h2 a[href]` (also 10 matches). Per-page domain deduplication prevents the same company appearing twice if Mojeek returns two paths for the same domain.

**What can go wrong.** If the page contains fewer than 300 characters, it is treated as an error response. Mojeek does not currently implement CAPTCHA pages; HTTP errors are transient network issues.

**Pagination.** Next-page links use `a.next[href]` or `a[rel="next"][href]`. The engine follows up to `PAGES_PER_QUERY` pages (default 5).

---

### DuckDuckGo (DDG Lite)

**Why chosen.** DDG has its own index (a mix of Bing results and its own crawler), distinct from Mojeek and Yahoo. The Lite endpoint (`lite.duckduckgo.com`) is significantly harder to block than the main endpoint — it is a simple POST endpoint with no JavaScript requirement and minimal bot detection.

**How it works.** DDG Lite is queried via POST to `https://lite.duckduckgo.com/lite/` with form data `{q: query, s: 0, kl: wt-wt, kp: -1}`. The `kl` parameter sets worldwide results; `kp: -1` turns off SafeSearch. The `s` parameter is the pagination offset (0, 25, 50...).

**HTML structure.** Each result is an `<a class="result-link" href="...">` anchor. The snippet is in the next sibling `<td class="result-snippet">`. Unlike the main DDG endpoint, URLs in Lite are direct — not wrapped in redirect URLs — so no URL decoding is needed.

**Selectors.** Primary: `a.result-link[href]`. The snippet requires traversing to the parent `<tr>` and finding the next sibling `<tr>` containing `td.result-snippet`.

**Special handling — HTTP 202.** DDG Lite returns HTTP 202 when it detects a bot challenge. The page is small (~3–5 KB), contains no result selectors, and is distinct from HTTP 403/429. HTTP 202 is transient (not a permanent block) and is resolved by a fresh warmup. The engine logs a clear warning, does not set `is_banned`, and allows the run to continue.

**Session warmup.** The DDG warmup (a GET to `https://duckduckgo.com/`) must run immediately before DDG's first search request — within 2 seconds. Running it earlier (e.g. before Mojeek processes all queries) causes the session cookies to expire by the time DDG's turn comes. The warmup injects harvested cookies into the shared httpx session.

**What can go wrong.** HTTP 202 (stale session — warmup too early). CAPTCHA (rare, IP flagged). Silent challenge page (page is small but not 202 — checked by size + selector count).

---

### Yahoo

**Why chosen.** Yahoo maintains its own search index (separate from Bing, despite a historical partnership). It has excellent UK coverage and generally returns 10 results per page with good geographic relevance for city-level queries.

**How it works.** Yahoo is queried via GET to `https://search.yahoo.com/search?p={query}&b=1&pz=10&vl=lang_en&fl=1`. The `b` parameter is the result offset (1-based, step 10). `pz=10` requests 10 results.

**HTML structure — dual pattern.** Yahoo serves result links in two different anchor patterns in the same page. Approximately 7 results use Pattern A: `div.compTitle > a[href]` (direct child anchor). Approximately 3 results use Pattern B: `div.compTitle > h3 > a[href]` (anchor wrapped in an h3). A selector using only Pattern A misses 30% of results. The combined selector `div.compTitle > a[href], div.compTitle > h3 > a[href]` picks up all 10.

**URL extraction.** Yahoo wraps every result URL in a redirect: `https://r.search.yahoo.com/_ylt=.../RU=https%3A%2F%2Factual-url.com/RK=2/...`. The real URL is extracted from the `/RU=` path segment: `href.split('/RU=')[1].split('/')[0]` then URL-decoded.

**Title contamination fix (CHANGE 2).** Yahoo's result title nodes sometimes contain the URL and breadcrumb path bleeding into the text: `"Philip James https://www.philipjames.co.uk › property"`. After extracting the title text, a regex strips everything from `https?://` onwards, collapses double spaces, and splits on breadcrumb separators (`›`, `»`).

**Sitelink dedup.** Yahoo can return multiple URLs for the same domain (sitelinks). Per-domain deduplication within each page prevents the same company from occupying multiple result slots.

**Session warmup.** A GET to `https://search.yahoo.com/` immediately before the first Yahoo search harvests session cookies that Yahoo's edge layer checks before serving results. Without this warmup, Yahoo returns HTTP 500 when the same IP has recently hit other search engines.

**What can go wrong.** HTTP 500 (rate-limit block — warmup must run). CAPTCHA (rare). Selector drift (HTML structure changes — fallback selector scans all `/RU=` hrefs).

---

### Bing

**Why chosen.** Bing has its own large index and good UK coverage. Its RSS feed endpoint provides clean machine-readable results that can be parsed with the standard library's `xml.etree.ElementTree` — no BeautifulSoup needed.

**How it works.** Bing is queried via GET to `https://www.bing.com/search?q={query}&format=RSS&first={offset}&mkt=en-US&cc=US&setlang=en-US&ensearch=1&count=10`. The `format=RSS` parameter requests an RSS XML feed instead of HTML.

**Geo-override headers.** Without special headers, Bing localises results to the client's IP geolocation. From a non-US/UK IP this returns results in the local language. The headers `X-MSEdge-ClientIP: 72.21.91.8`, `X-MSEdge-Market: en-US`, and `X-Search-Location: lat:40.7128;long:-74.0060;re:1000` tell Bing to serve US English results. These are set per-request without polluting the shared session used by other engines.

**English result check.** Even with geo-override headers, some IPs receive geo-wrong results. Every result is checked: if more than 30% of title characters are non-ASCII, or the description contains locale URL patterns (`/de/`, `hl=ja`, etc.), the result is rejected. If all results on page 1 fail this check, Bing is marked as banned and no further pages are fetched.

**Proxy support.** The `BING_PROXY` setting in `config.py` routes all Bing requests through a dedicated proxy client. This client is never shared with other engines. Without a proxy, Bing is the least reliable engine and should be treated as optional.

**What can go wrong.** Geo-wrong results from some IPs (set `BING_PROXY`). RSS XML parse error (rare, falls back to HTML parsing). IP flagged (no proxy — set `BING_PROXY` and use a residential proxy).

---

## Part 4: Session Management — The Warmup Architecture

This is the most important architectural decision in Phase 1. Understanding it is essential for anyone debugging a DDG HTTP 202 or Yahoo HTTP 500 error.

### What HTTP 202 means in DDG's context

DuckDuckGo uses HTTP 202 as a bot-detection signal, not as its standard "Accepted" semantic. When DDG Lite returns HTTP 202, the response body is a challenge page (a few kilobytes of JavaScript that checks browser fingerprints). It is not a CAPTCHA — there is no puzzle to solve. It means: "we think you're a bot because your session looks stale." The fix is a fresh warmup.

### Why a stale session causes it

DDG Lite checks that the POST request comes from a session that has recently loaded the DDG homepage. The homepage sets session cookies (`dcm`, `l`, `s`) that the Lite endpoint validates. If those cookies are absent or expired, DDG returns 202 instead of results.

### Why the v12 pre-flight warmup broke the combined run

In the previous version, all warmups ran in a single pre-flight block before the engine loop:

```python
# v12 (broken):
_warmup_ddg()
_warmup_yahoo()
for engine in engines:
    run_engine(engine)  # Mojeek runs first, takes 12s × N queries
                        # By the time DDG runs, warmup is 120s old → HTTP 202
```

Mojeek processes all queries before DDG starts. At 12 seconds per query (network + delays) with 10 queries, Mojeek takes ~120 seconds. The DDG warmup session expires within ~30–60 seconds. DDG returns HTTP 202 for every query.

### The v13 fix: warmup inside the engine loop

```python
# v13 (correct):
for engine_name in engines:
    _do_engine_warmup(engine_name)  # ← runs immediately before this engine's first query
    run_engine(engine_name)         # gap between warmup and first request: ≤2 seconds
```

Moving the warmup inside the loop, immediately before the engine's first request, guarantees a fresh session regardless of how long previous engines took. The warmup-to-request gap is always ≤2 seconds.

This same fix applies to Yahoo's HTTP 500: the warmup must run immediately before Yahoo's first request, after however long Mojeek and DDG took.

---

## Part 5: Data Cleaning Pipeline

Every URL returned by search engines goes through `pipeline/data_cleaner.py` before being written to output. The pipeline runs in this order:

**1. Ad redirect detection (CHANGE 1, Category 1).** Before any record is created, the URL is checked against known ad redirect patterns: `bing.com/aclick`, `google.com/aclk`, `googleadservices.com`, `doubleclick.net`, etc. Also, any URL longer than 300 characters containing `?ld=` or `/aclick` is classified as a tracker redirect. These return `None` immediately — no `CleanRecord` is created, no CSV row is produced.

**2. URL normalisation.** `normalise_url()` strips tracking parameters (`utm_*`, `fbclid`, `gclid`, `ref`, `referrer`, `_ga`, etc.) from query strings, normalises the scheme to lowercase, strips URL fragments (`#...`), and removes trailing slashes from paths. This ensures that `example.com/?utm_source=google` and `example.com/` are treated as the same URL.

**3. Root URL normalisation.** Company homepages are more valuable than deep subpages. `_normalise_to_root()` collapses any URL with 2+ path segments to its homepage root: `example.co.uk/services/block-management` → `example.co.uk/`. This reduces duplicate detection false negatives and produces cleaner output.

**4. Domain extraction.** `base_domain()` extracts the registrable domain without `www.` and without port numbers. This is the deduplication key.

**5. Hard exclusions.** The domain is checked against `_ALWAYS_EXCLUDED` — a set containing social platforms (Facebook, LinkedIn, Instagram, Twitter/X, TikTok, YouTube, Snapchat, Threads, WhatsApp, Telegram, Discord, Twitch, Vimeo, Dailymotion), encyclopedias (Wikipedia), and other known junk. Any match returns `None`.

**6. Parasite domain detection.** Domains matching the pattern `*.co.uk.seowebstat.com` or similar multi-dot parasites are rejected. These are SEO tracking sites that mirror real domains in their own hostname.

**7. Domain-level deduplication.** The `DataCleaner` instance maintains a `_seen_domains` set shared across all engines and all queries in a session. The first time a domain is encountered, it is added and the record is kept. Any subsequent result for the same domain (from any engine, any query) is silently dropped.

**8. Flagging (directory/pattern assessment).** `_assess()` checks whether the domain is in `_DIRECTORY_DOMAINS` (aggregators, job boards, review sites, classified ads, blog platforms), whether the domain ends in `.gov.uk` or `.org.uk`, whether the URL matches suspicious patterns (very long URL, results/search path, binary file extension, job/career/press/blog/category paths, US city in query with `.co.uk` domain). Flagged records are kept in the output but marked with `YES` and a reason string.

**9. Scoring.** `_score()` assigns a confidence score: +1 for `.co.uk` domain when a UK city is in the query, +1 if the URL path contains service keywords, −1 for deep paths (3+ segments), −2 for listicle URL patterns (top-10, best-, etc.).

**10. CHANGE 1, Category 3 — Structural garbage detection.** After the `CleanRecord` is created, the title text is tokenised and compared against the query tokens. If there is zero word overlap (words ≥4 characters, stop words excluded), the record is assigned score −5 and `flag_reason='irrelevant'`. This catches results like `stackoverflow.com` returning an "Angular" question for a "property managers Manchester" query.

---

## Part 6: Contact Enrichment — Two-Pass Strategy

### Why Pass 1 (HTTP) is fast but fails on SPAs

`requests.get()` downloads the raw HTML response exactly as the server sends it. For a traditional server-rendered website, the HTML contains all content including contact emails. For a React, Angular, or Next.js SPA, the HTML response is a skeleton: a `<div id="root"></div>` and a `<script>` tag. The actual page content — including the contact page — is injected by JavaScript after the browser has downloaded and executed the bundle. Plain HTTP GET sees only the skeleton.

### Why Pass 2 (Playwright) is slow but catches the rest

Playwright launches a real Chromium browser, navigates to the page, waits for `domcontentloaded`, and reads `page.content()` after JavaScript has executed. This is the same page content a real user sees. The cost is ~3–5 seconds per page load.

Pass 2 is deliberately the fallback, not the primary. The majority of company websites are server-rendered or at least expose their contact details in static HTML. Launching a full browser for every site would increase runtime by 5–10×.

### The visit sequence

Both passes follow the same page visit order for each company:
1. Homepage (always visited first)
2. `/contact` or `/contact-us`
3. `/about` or `/about-us`

**Early exit:** as soon as a score-1 or score-2 email is found (personal name or priority generic), no further pages are visited for that company.

### Cloudflare email decoding

Cloudflare's email-protection replaces `user@company.com` with a hex-encoded string: `<a href="/cdn-cgi/l/email-protection#1a727f7676...">`. The encoding is XOR: the first byte is the key; every subsequent byte is XOR'd with the key to produce the plaintext character. `decode_cloudflare_email()` implements this: `bytes.fromhex(encoded)`, take `enc[0]` as key, decode remaining bytes. Two HTML patterns are recognised: the `href` pattern and `data-cfemail` attribute pattern.

### Email scoring hierarchy

Emails are scored so that the most valuable contact is always preferred:
- Score 1 (best): personal name address — `john.smith@company.com`. Contains no generic keywords.
- Score 2: high-priority generic — `info@`, `hello@`, `contact@`, `enquiries@`, `enquiry@`. Addressed to a person who reads it.
- Score 3: other generic — `support@`, `accounts@`, `sales@`, `manager@`. Monitored by multiple people.
- Score 999 (junk): filtered out entirely — `noreply@`, `gdpr@`, addresses from junk domains like `sentry.io`.

`best_email()` returns the email with the lowest score from a list, ignoring all 999-scored addresses.

### Phone extraction

Two strategies in priority order:
1. `tel:` href attributes — `<a href="tel:+441234567890">`. Highest confidence; explicitly formatted by the website owner.
2. Regex matching — three patterns covering international (`+44 20 7123 4567`), bracketed (`(020) 7123 4567`), and plain (`020 7123 4567`) formats. Only fired when no `tel:` links are found.

Deduplication is done by digit-only string (the same number written differently appears once).

### Cookie banner dismissal

Before reading page content in Pass 2, Playwright attempts to click cookie consent buttons using a list of CSS selectors (`button:has-text("Accept all")`, etc.). This is silent — any click failure is swallowed. Undismissed banners overlay the page but rarely obscure email addresses in `href` attributes or text nodes.

### Resource blocking

The Playwright browser context blocks images, fonts, videos, and common tracking scripts (`google-analytics`, `doubleclick`, `facebook.net`). This reduces page load time significantly — a page that takes 4 seconds with assets loads in ~1 second without them.

### Browser memory management

After processing every `browser_restart_every` sites (default 150), the browser process is closed and relaunched. A long-running Chromium instance accumulates memory from cached pages, DOM trees, and JavaScript heaps. Periodic restarts prevent the process from consuming multiple gigabytes of RAM on large runs.

---

## Part 7: Lead Quality Scoring

### Why Phase 1 cannot assess lead quality

Phase 1 only collects URLs — it does not visit company websites. The scraper has no idea what is on the page; it only knows the URL came from a search result for a specific query. A URL like `checkatrade.com/search?query=block+managers+manchester` looks superficially like a lead but is a directory listing. A URL like `alphablockmanagement.co.uk` looks generic but is almost certainly a real lead. Phase 1 flags the first as a directory (domain in `_DIRECTORY_DOMAINS`) but cannot distinguish the second from a false positive without reading the page content.

### How auto-expanding the query into keywords works

`score_relevance(html, query)` in `core/relevance.py`:
1. Extracts tokens from the query — words ≥4 characters, after removing stop words (`the`, `and`, `for`, `in`, `of`, etc.)
2. Strips HTML with BeautifulSoup to get the page body text
3. Counts how many query tokens appear in the body text
4. Computes `keyword_match_pct = hits / token_count × 100`

For the query `"block management companies London"`, the meaningful tokens are `block`, `management`, `companies`, `london`. A real block management company's homepage will use all four words. A plumber's homepage will use none.

### What HOT/WARM/COLD/NOISE means

- **NOISE:** Job board, directory listing, or news article signals are detected regardless of keyword match. These are never leads.
- **HOT:** ≥40% keyword match AND at least one contact signal (`contact us`, `get in touch`, `enquire`) or services signal (`our services`, `we offer`, `we specialise`). This combination strongly indicates a real company actively offering the service you searched for.
- **WARM:** ≥20% keyword match OR an "About Us" signal. Plausibly relevant — the company exists and has some connection to the query.
- **COLD:** Below all thresholds. May be tangentially relevant; manual review needed.

### Why this approach works for any query type

The scoring system is entirely driven by the user's search query — there is no hardcoded list of property keywords. Searching for `"dental practices Manchester"` produces tokens `dental`, `practices`, `manchester`. A dental practice's homepage scores HOT. A dental equipment supplier scores WARM. A job board advertising dental receptionist roles scores NOISE.

---

## Part 8: Runtime Controls Architecture

### How `msvcrt.kbhit()` works on Windows

On Windows, `msvcrt.kbhit()` is a non-blocking check that returns True if a key has been pressed and is waiting in the keyboard buffer. `msvcrt.getch()` reads one byte from the buffer without waiting. This allows single-key detection (no Enter required) in a tight polling loop with 50 ms sleep between polls, consuming negligible CPU.

### How `select.select()` works on Unix

On Mac/Linux, stdin is a file descriptor. `select.select([sys.stdin], [], [], 0.2)` blocks for up to 0.2 seconds waiting for stdin to become readable. When the user types a line and presses Enter, `sys.stdin.readline()` reads it. This requires Enter but is the only reliable portable approach without installing a terminal library like `curses`.

### The State class and daemon thread

`State` is a plain class with three boolean attributes: `paused`, `stop`, and `handoff`. The `ControlListener` runs in a daemon thread — a background thread that is automatically killed when the main thread exits. The main loop checks `state.paused` and `state.stop` at safe checkpoints (between requests, between queries). There is no locking because boolean assignment is atomic in CPython.

### What each key does

- `P` — toggles `state.paused`. The main loop calls `wait_if_paused()` which polls every 300 ms until `paused` is cleared.
- `R` — clears `state.paused` (explicit resume, useful when already paused).
- `Q` — sets `state.stop = True`. The main loop exits at the next checkpoint and saves all progress.
- `S` — prints `ctx["found"]` and `ctx["done"]` counters to the console.
- `W` — sets both `state.handoff = True` and `state.stop = True`. Phase 1 exits cleanly. The `main.py` orchestrator detects `handoff=True` and shows the Phase 2 prompt.

### The `command.txt` file interface

Writing a command to `command.txt` is equivalent to pressing the corresponding key. The file is checked at every site boundary in both passes. Valid commands: `pause`, `resume` (or `r`), `stop` (or `q`), `fresh` (deletes the checkpoint). After reading, the file is cleared (overwritten with empty string). This interface enables remote control over SSH or from a scheduled task.

### AutoSaver — background thread saves

`AutoSaver` runs in a daemon thread and calls `save_output()` every `autosave_interval` seconds (default 60). This is in addition to the per-site saves (every 10 sites). The combination ensures that on a slow run processing sites that take 30+ seconds each, data is never more than 60 seconds behind disk. The thread is stopped by setting `_stopped = True` after each pass completes.

### `wait_for_internet()` — connectivity auto-pause

When `has_internet()` returns False (TCP connection to `8.8.8.8:53` fails), `wait_for_internet()` sets `state.paused = True` and polls every 30 seconds. When connectivity returns, `paused` is cleared and the run continues automatically. This handles VPN drops, router reboots, and ISP outages during long overnight runs without requiring user intervention.

---

## Part 9: Checkpointing — Crash Safety

### Why atomic writes matter

A checkpoint file written with `open(path, 'w').write(json.dumps(data))` has a race condition: if the process is killed between the OS truncating the file and finishing the write, the file is empty or partial — unreadable JSON that returns `(set(), {})` on next load, losing all progress.

`os.replace()` is atomic on POSIX systems and on Windows NTFS (Python 3.3+). It atomically renames the `.tmp` file to the final path. The OS guarantees that readers see either the old file or the new file, never a half-written state.

### What happens without atomic writes

If the process is killed mid-write without atomics:
- The checkpoint file is empty or truncated
- `load_checkpoint()` returns `(set(), {})` — treats it as a fresh start
- All processed companies are re-processed from scratch
- All collected contacts are lost

### The checkpoint JSON structure

```json
{
  "done": ["acme corp", "globex ltd", "initech"],
  "found": {
    "acme corp": {
      "name": "Acme Corp",
      "website": "https://acme.com",
      "email": "info@acme.com",
      "phone": "+44 20 7000 0000",
      "category": "Block Management"
    }
  }
}
```

`done` is the set of company keys (lowercased names) that have been processed. `found` is the dict of contacts found. Both are loaded at startup and merged with any existing output CSV.

### How resume works

On startup, `load_checkpoint()` returns `(done, found)`. `load_existing_output()` reads any prior output CSV and merges into `found`. The `done` set determines which companies are skipped in Pass 1. Any company in `found` is skipped in Pass 2. This means a resumed run continues exactly where it left off.

### When the checkpoint is deleted

The checkpoint is deleted only after a clean full completion (`all_done = not state.stop`). If the user pressed Q, the checkpoint is kept so the next run can resume. If Phase 1 exited via W key (handoff), the checkpoint is kept so Phase 1 can be re-run later with more queries while Phase 2 runs on the existing results.

---

## Part 10: Output Format

### Phase 1 output

The CSV and Excel file are written to `outputs/leads_YYYY-MM-DD_HH-MM.csv` and `.xlsx`. Records are sorted by `score` descending before writing — highest-confidence leads appear first.

**Colour coding in Excel:**
- Header row: dark navy (`#1F4E79`) with white bold text
- Flagged rows (`YES`): yellow background (`#FFFF00`) with dark red bold text — a visual warning
- Alternating rows: light blue (`#EBF3FB`) for readability on large datasets
- Website URL column: hyperlinked and styled blue, clickable directly in Excel

**Summary sheet:** shows total records, unique domains, flagged count, records per engine, and top queries by records found. Useful for understanding which engines and queries produced the most results.

**CSV companion:** always written alongside the Excel file. UTF-8 with BOM (`utf-8-sig`) so it opens correctly in Excel without conversion.

### Phase 2 enriched output

Adds `Email`, `Phone`, `Lead Quality`, and `Keyword Match %` columns. The `lead_quality` column uses colour-coded text in Excel: HOT=red, WARM=orange, COLD=blue, NOISE=grey. The Run Stats sheet shows per-pass breakdown, success rates, and total elapsed time.

---

## Part 11: Configuration Reference

### `config.py` — Phase 1

| Setting | Default | When to change |
|---|---|---|
| `ENGINES_PRIORITY` | `['mojeek','duckduckgo','yahoo','bing']` | Reorder or remove engines |
| `PAGES_PER_QUERY` | `5` | Increase for more results, decrease for faster runs |
| `BING_PROXY` | `''` | Set to a residential proxy URL for reliable Bing results |
| `DELAY_BETWEEN_REQUESTS` | `(3, 8)` | Increase if getting 429 errors |
| `DELAY_BETWEEN_PAGES` | `(8, 15)` | Increase if getting 429 errors on pagination |
| `DELAY_BETWEEN_QUERIES` | `(20, 45)` | Increase for slower, safer pacing |
| `DELAY_BETWEEN_ENGINES` | `(60, 120)` | Increase to reduce IP-level heat across engines |
| `CONNECT_TIMEOUT` | `10` | Increase on slow connections |
| `READ_TIMEOUT` | `30` | Increase for very slow servers |
| `MAX_RETRIES` | `4` | Increase for unreliable networks |
| `COOLDOWN_ON_429` | `600` | Seconds to wait after a 429 response |
| `CHECKPOINT_EVERY` | `50` | Save checkpoint after every N new records |

### `config.yaml` — Phase 2

| Setting | Default | When to change |
|---|---|---|
| `http_timeout` | `[4, 6]` | Increase for slow websites |
| `playwright_timeout` | `8000` | Increase (ms) for JS-heavy sites |
| `browser_restart_every` | `150` | Decrease if browser memory grows too large |
| `stop_at` | `"23:00"` | Set to `""` to disable time-based stopping |
| `autosave_interval` | `60` | Decrease for more frequent saves |
| `rate_limit.min_seconds` | `0.1` | Increase to slow down Pass 1 |
| `rate_limit.max_seconds` | `0.5` | Increase to slow down Pass 1 |
| `contact_paths` | `['/contact','/contact-us','/about','/about-us']` | Add site-specific paths |

---

## Part 12: Running the System — Full Walkthrough

### Step 1: Installation

```bash
git clone https://github.com/FAAQJAVED/leadhunter-pro
cd leadhunter-pro
pip install -r requirements.txt
python -m playwright install chromium
```

### Step 2: Write queries.txt

```bash
cp queries.txt.example queries.txt
```

Edit `queries.txt` — one query per line, natural language, service + location:
```
block management companies London
residential letting agents Manchester
property management firms Birmingham
facilities management companies Leeds
```

### Step 3: Run diagnose.py first

```bash
python diagnose.py
```

Check that at least 2 of the 3 default engines show `[OK]` (≥10 results). If DDG shows HTTP 202, re-run immediately (usually resolves on retry). If Yahoo shows HTTP 500, wait 30 seconds and try again. If Mojeek shows 0 results, check your internet connection.

### Step 4: Run main.py

```bash
python main.py
```

The terminal shows a progress bar and per-query result counts. Press `S` to see totals. Press `P` to pause if needed.

### Step 5: Understand the terminal output

```
[14:32:01] Mojeek       | "block management London" | Page 5 | +8 results (Total: 247)
```

Format: `[timestamp] engine | query | page | +new_this_page (running_total)`.

The progress bar shows: `Mojeek | block man` `[████████░░░░░░]| 23/50 [01:47<02:14, 0.18 engine-query/s]`

### Step 6: Phase 2 prompt

When Phase 1 completes (or when you press `W`):
```
══════════════════════════════════════════════════════════
  Phase 1 complete  ─  312 leads collected

  Proceed to Phase 2?
  [Y] Yes  — extract emails, phones & score lead quality
  [N] No   — save CSV and exit
  [V] View — open output folder first, then decide
══════════════════════════════════════════════════════════
  Choice [Y/N/V]:
```

### Step 7: What to do if an engine fails

- **DDG HTTP 202:** re-run `python diagnose.py --ddg`. Usually resolves immediately.
- **Yahoo HTTP 500:** wait 2 minutes, re-run. If persistent, run `--yahoo` in isolation.
- **Bing geo-wrong:** set `BING_PROXY` in `config.py` or run with a VPN.
- **Mojeek 0 results:** check internet connection; Mojeek has very low failure rate.

### Step 8: Resume an interrupted run

```bash
python main.py
# → "CHECKPOINT FOUND: Queries done: 8, Records: 247"
# → "Resume from checkpoint? (Y/N):" → Y
```

### Step 9: Add more queries and append

Add new queries to `queries.txt`. Re-run with `--resume`. Only new (unprocessed) queries will run; completed ones are skipped. New results are appended to the same output files.

---

## Part 13: Common Issues and Solutions

| Issue | Cause | Fix |
|---|---|---|
| DDG HTTP 202 | Stale session — warmup-to-request gap > ~30 s | Re-run immediately; warmup inside engine loop fixes this in normal runs |
| Yahoo HTTP 500 | Rate-limit block after other engines hit same IP | Wait 2 min; run `--yahoo` in isolation first |
| Bing geo-wrong results (0 passing English check) | Client IP geolocation overrides X-MSEdge headers | Set `BING_PROXY` in `config.py` or use a VPN |
| Playwright `ModuleNotFoundError` | Not installed | `pip install playwright && python -m playwright install chromium` |
| Missing brotli | Not installed | `pip install brotli` (fixes encoding garbling on some engines) |
| Checkpoint corrupt | Disk full or power loss during write | Delete `checkpoints/checkpoint.json`; use `--fresh` |
| Output directory missing | First run on new machine | Created automatically on startup |
| Low disk space warning | Large run on nearly-full drive | Free ≥500 MB or change `OUTPUT_DIR` in `config.py` |
| HTTP 202 persists after retry | IP flagged temporarily | Wait 10 minutes; use a different IP or VPN |
| Yahoo titles contain URLs | Yahoo HTML change | Fixed in CHANGE 2: `_clean_yahoo_title()` strips URL bleeding |
| `bing.com/aclick` URLs in output | Ad redirect not caught | Fixed in CHANGE 1: ad redirect check runs before `CleanRecord` creation |

---

## Part 14: Design Decisions and What Was Rejected

**Why Selenium was not used.** Playwright is faster (Chromium launches in ~1 s vs ~3 s for Chrome with Selenium), has a cleaner Python API, and is better maintained. The `sync_playwright()` API is synchronous, matching the rest of the codebase without requiring asyncio.

**Why per-query domain blacklists were rejected.** An early design added a `blacklist.txt` per query type (e.g. "always exclude these domains for property queries"). This was rejected because it is not general-purpose — it requires manual curation for every new query category and becomes outdated as domains change. The universal filters in `data_cleaner.py` (ad redirects, social platforms, structural garbage scoring) apply to any query without configuration.

**Why warmup is per-engine, not per-session.** A single shared warmup at session start works only when engines run back-to-back with minimal delay. In practice, Mojeek's runtime for 20 queries is ~10–15 minutes. DDG's session cookies expire in under a minute of inactivity. Per-engine warmup is the only reliable solution.

**Why Brave and Startpage were evaluated and dropped.** Two additional engines were tested during development. Brave Search DNS was blocked on most residential and cloud IPs — the engine returned NXDOMAIN or connection-refused regardless of User-Agent or headers, making it unreliable for any practical run. Startpage permanently blocks all automated clients: it returns a 403 or a bot-detection page after a single query regardless of headers or pacing. Neither engine is present in the codebase. The final system ships exactly four engines: Mojeek, DuckDuckGo, Yahoo, and Bing — all confirmed working with the session management described in this document.

**Why Yahoo title contamination is fixed at parse time, not clean time.** The title text extracted by BeautifulSoup already contains the URL before any other processing. Fixing it in `data_cleaner.py` after the fact would require re-parsing the raw text, which is no longer available at that point. The fix belongs in `_parse_primary()` and `_parse_fallback()` in `engines/yahoo.py`, applied immediately after `self._text()` extraction.

**Why `sync_playwright()` uses `__enter__()` / `__exit__()` instead of `with`.** The `with sync_playwright() as p:` pattern raises a `ContextVar` error in some Windows + Python 3.12 environments due to how Playwright manages its internal event loop context. Using `_pw_ctx = sync_playwright(); pw = _pw_ctx.__enter__()` and `_pw_ctx.__exit__(None, None, None)` in a `finally` block achieves the same lifecycle management without triggering the incompatibility.
