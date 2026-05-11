# LeadHunter Pro

**Production-grade Python lead generation engine — scrapes 4 independent search engines simultaneously, enriches every result with email and phone, and scores each lead HOT / WARM / COLD for prioritised outreach. Type a query, get a ready-to-use Excel lead list.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/FAAQJAVED/Leadhunter_Pro/actions/workflows/ci.yml/badge.svg)](https://github.com/FAAQJAVED/Leadhunter_Pro/actions)
[![Tests](https://img.shields.io/badge/tests-72%20passing-brightgreen)](tests/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/FAAQJAVED/Leadhunter_Pro)

---

Found this useful? A ⭐ on GitHub helps other developers find it.

---

> **Responsible use:** Only scrape websites you have permission to access.
> Always check a site's `robots.txt` and terms of service before running
> LeadHunter Pro against it at scale.


## Table of Contents

[Preview](#preview) · [What It Does](#what-it-does) · [Use Cases](#use-cases) · [How It Works](#how-it-works) · [Features](#features) · [Performance](#performance) · [What Data You Get](#what-data-you-get) · [Quick Start](#quick-start) · [Blueprint Reference](#blueprint-reference) · [Run Phases Separately](#or-run-phases-separately) · [Configuration](#configuration) · [Runtime Controls](#runtime-controls) · [Output Format](#output-format) · [Diagnose Your Engines](#diagnose-your-engines) · [Architecture Notes](#architecture-notes) · [Tech Stack](#tech-stack) · [Project Structure](#project-structure) · [Requirements](#requirements) · [Troubleshooting](#troubleshooting) · [B2B Lead Toolkit](#part-of-the-b2b-lead-toolkit) · [License](#license)

---

## Preview

| Phase 1 — Scraping                                       | Phase 2 — Enrichment                                     |
| --------------------------------------------------------- | --------------------------------------------------------- |
| ![Phase 1 scraping in progress](assets/phase1-scraping.png) | ![Phase 2 enrichment running](assets/phase2-enrichment.png) |

| Excel Output                                               | Diagnose Output                                       |
| ---------------------------------------------------------- | ----------------------------------------------------- |
| ![Colour-coded Excel output](assets/excel-output-sample.png) | ![Diagnose terminal output](assets/diagnose-output.png) |

---

## What It Does

1. **Reads `queries.txt`** — one search query per line (e.g. `property managers manchester`)
2. **Phase 1 — Scrapes 4 search engines** (Mojeek, DuckDuckGo, Yahoo, Bing) for each query, deduplicates results across engines, and saves a lead CSV.
3. **Phase 2 — Enriches every lead** by visiting each website: Pass 1 (fast HTTP GET) then Playwright fallback for JS-rendered sites.
4. **Scores each lead** HOT / WARM / COLD / NOISE based on keyword matching against the original query — prioritised for outreach.
5. **Outputs a styled Excel file** — colour-coded by score, sorted by quality, hyperlinked websites, and a Summary sheet with engine statistics.

Each engine runs in its own session with a warmup request to avoid HTTP 202 bot challenges. Results are deduplicated across all four engines using URL normalisation and domain deduplication before enrichment begins. A built-in `diagnose.py` tool checks each engine's health before a run.

---

## Use Cases

| Who uses it | What they do | Example query |
|---|---|---|
| **Sales teams** | Generate targeted prospect lists for cold email campaigns | `"accountants london"` → 400+ HOT leads with email |
| **Marketing agencies** | Deliver multi-source lead lists for any UK industry vertical | `"estate agents birmingham"` → enriched Excel in 2 hours |
| **Freelance lead gen** | Automate research for clients across any niche and geography | Any query → score-sorted Excel ready for CRM import |
| **Recruiters** | Identify employers in a sector and geography with direct contact | `"law firms edinburgh"` → HR emails and direct lines |
| **Market researchers** | Map a category using 4 independent search indexes simultaneously | Any query → deduplicated coverage from all 4 engines |
| **SDRs** | Build daily outreach lists with pre-scored priority rankings | Multiple queries → HOT leads on top, COLD at bottom |

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1 — Search Scraping                                      │
│                                                                 │
│  queries.txt  ──►  Mojeek  ──┐                                  │
│                  DuckDuckGo ─┼──► Dedup ──► data_cleaner.py    │
│                  Yahoo      ─┤             ├── URL normalise    │
│                  Bing       ─┘             ├── Domain dedup     │
│                                            ├── Ad filter        │
│                                            ├── Social filter    │
│                                            └── Scoring          │
│                         leads_YYYY-MM-DD.csv / .xlsx            │
└──────────────────────────────┬──────────────────────────────────┘
                               │  Y to proceed (or W key mid-run)
┌──────────────────────────────▼──────────────────────────────────┐
│  PHASE 2 — Contact Enrichment                                   │
│                                                                 │
│  leads.csv ──► Pass 1 (HTTP GET) ──► email + phone found?      │
│                     │ No                                        │
│                     ▼                                           │
│               Pass 2 (Playwright) ──► email + phone found?     │
│                     │                                           │
│                     ▼                                           │
│               score_relevance() ──► HOT / WARM / COLD / NOISE  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  OUTPUT                                                         │
│  enriched_leads_YYYY-MM-DD.xlsx  (sorted by quality + score)   │
│  enriched_leads_YYYY-MM-DD.csv   (backup, always written)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

| Feature                               | Detail                                                                                               |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **4 search engines**            | Mojeek, DuckDuckGo, Yahoo, Bing — independent indexes, combined deduplication                       |
| **Per-engine session warmup**   | Runs immediately before each engine's first request (≤2 s gap) — prevents HTTP 202 bot challenges  |
| **Dual-pattern Yahoo selector** | Pattern A (`div.compTitle > a`) + Pattern B (`div.compTitle > h3 > a`) — catches all 10 results |
| **Cloudflare email decoding**   | XOR-decodes `cdn-cgi/l/email-protection` and `data-cfemail` attributes                           |
| **Two-pass enrichment**         | Pass 1: fast HTTP GET · Pass 2: Playwright headless Chromium fallback for JS-rendered sites         |
| **Email scoring**               | Personal name = best (1), priority generic (2), generic (3), junk filtered (999)                     |
| **Lead quality scoring**        | HOT / WARM / COLD / NOISE — query-keyword matching, works for any industry                          |
| **Live keyboard controls**      | `P` pause · `R` resume · `Q` quit · `S` status · `W` hand off to Phase 2               |
| **Crash-safe checkpointing**    | Atomic writes (`os.replace`) — resume from any interruption with zero data loss                   |
| **Internet auto-pause**         | Detects connectivity loss, pauses, and auto-resumes when connection returns                          |
| **Background auto-save**        | Saves every 60 s in addition to per-site saves                                                       |
| **Universal Phase 1 filters**   | Ad redirect URLs · extended social platforms · structural garbage (score −5)                      |
| **Formatted Excel output**      | Score-sorted, hyperlinked, colour-coded + HOT/WARM/COLD badges + Summary sheet                       |

---

## Performance

| Mode | Queries | Leads generated | Enrichment | Time |
|---|---|---|---|---|
| Single query | 1 | 20–60 leads | All 4 engines | 3–8 min |
| Small batch | 5–10 queries | 100–300 leads | Full 2-pass | 20–40 min |
| Overnight run | 50+ queries | 800–2,000 leads | Full 2-pass | 3–8 hours |

> **Real run:** `"property managers manchester"` — 1 query across all 4 engines, **62 unique leads from Mojeek alone** (pages 1–9), full enrichment pipeline applied. HOT leads sorted to top with 100% keyword match.

---

## What Data You Get

| Field | Example |
|---|---|
| Company Name | Prime Residential |
| Website | https://primeresidentialpm.com/ |
| Email | manchester@primeresidentialpm.com |
| Phone | 01612413335 |
| Lead Quality | HOT |
| Keyword Match % | 100 |

See [`assets/sample_output.csv`](assets/sample_output.csv) for 20 rows of real output extracted from a live scrape.

---

## Quick Start

```bash
git clone https://github.com/FAAQJAVED/Leadhunter_Pro.git
cd Leadhunter_Pro
pip install -r requirements.txt
python -m playwright install chromium

# Add your queries (one per line)
cp queries.txt.example queries.txt
# Edit queries.txt with your search terms

# Check engines are healthy first
python diagnose.py

# Run Phase 1 (scraping) — prompted for Phase 2 (enrichment) at the end
python main.py
```

---

## Blueprint Reference

For a complete technical deep-dive — architecture decisions, engine behaviour, rate-limit strategy, scoring model, and extension guide — see [BLUEPRINT.md](BLUEPRINT.md).

---

## Or Run Phases Separately

```bash
# Phase 1 only — specific engines, specific query
python main.py --query "letting agents Manchester" --mojeek --ddg

# Phase 2 only — enrich an existing CSV
python enricher.py --input outputs/leads_2026-05-01.csv
```

---

## Configuration

### `config.py` — Phase 1 (scraper) settings

| Setting                    | Default                                    | Description                                                                      |
| -------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------- |
| `ENGINES_PRIORITY`       | `['mojeek','duckduckgo','yahoo','bing']` | Engine order                                                                     |
| `PAGES_PER_QUERY`        | `5`                                      | Result pages per query per engine                                                |
| `BING_PROXY`             | `''`                                     | Residential proxy URL for Bing geo-unlock. Format:`http://user:pass@host:port` |
| `DELAY_BETWEEN_REQUESTS` | `(3, 8)`                                 | Seconds between HTTP requests                                                    |
| `DELAY_BETWEEN_QUERIES`  | `(20, 45)`                               | Seconds between queries                                                          |
| `DELAY_BETWEEN_ENGINES`  | `(60, 120)`                              | Seconds between engine switches                                                  |

**Bing proxy options:**

```python
# Authenticated residential proxy
BING_PROXY = 'http://user:pass@uk.residential.proxy:8080'

# SOCKS5
BING_PROXY = 'socks5://user:pass@proxy-host:1080'
```

### `config.yaml` — Phase 2 (enricher) settings

```bash
cp config.example.yaml config.yaml
```

| Key | Default | Description |
|---|---|---|
| `output_format` | `xlsx` | Output format — `xlsx` or `csv` |
| `http_timeout` | `[4, 6]` | Pass 1 HTTP timeout range `[min, max]` in seconds |
| `playwright_timeout` | `8000` | Pass 2 Playwright page load timeout in milliseconds |
| `browser_restart_every` | `150` | Restart Chromium every N sites to prevent memory leaks |
| `stop_at` | `""` | Wall-clock auto-stop in 24h format — `""` = disabled (e.g. `"23:00"`) |
| `autosave_interval` | `60` | Background checkpoint save interval in seconds |
| `enricher_workers` | `5` | Concurrent worker count for Pass 1 HTTP enrichment |
| `rate_limit.min_seconds` | `0.1` | Minimum delay between HTTP requests |
| `rate_limit.max_seconds` | `0.5` | Maximum delay between HTTP requests |
| `GEO_SUSPECT_TLDS` | `[]` | TLDs flagged as geo-suspect — e.g. `['in', 'pk', 'ru']` |
| `score_boost_keywords` | `[]` | URL keywords that give a +1 score boost to a lead |
| `skip_email_keywords` | `[noreply, no-reply, …]` | Local-part patterns that discard an email entirely (score 999) |
| `generic_email_keywords` | `[info, admin, support, …]` | Generics used to assign email quality tier (2 or 3) |
| `junk_email_domains` | `[mailinator.com, …]` | Domains whose emails are always discarded |
| `contact_paths` | `[/contact, /about, …]` | Sub-pages visited per site in Pass 1 after the homepage |
| `locale` | `en-US` | Browser locale passed to Playwright for Pass 2 |
| `cookie_selectors` | `[…]` | Playwright selectors tried for cookie banner dismissal (10 defaults) |

---

## Runtime Controls

| Key   | Phase | Action                                           |
| ----- | ----- | ------------------------------------------------ |
| `P` | 1 & 2 | Pause / resume toggle                            |
| `R` | 1 & 2 | Resume if paused                                 |
| `Q` | 1 & 2 | Quit and save progress                           |
| `S` | 1 & 2 | Print current status                             |
| `W` | 1     | End Phase 1 early, go directly to Phase 2 prompt |

**Windows:** single key, no Enter required
**Mac / Linux:** type the letter then press Enter

**Automation:** write a command to `command.txt` (`pause`, `resume`, `stop`, `fresh`) — useful for scripting.

---

## Output Format

### Phase 1 output columns

| Column            | Description                                                              |
| ----------------- | ------------------------------------------------------------------------ |
| `Score`         | Confidence score (higher = more likely a real company homepage)          |
| `Company Name`  | Derived from domain (URL bleeding and breadcrumbs stripped)              |
| `Website URL`   | Normalised homepage URL (tracking params removed)                        |
| `Domain`        | Base domain (cross-engine dedup key)                                     |
| `Search Query`  | The query that found this result                                         |
| `Search Engine` | Engine that returned this result                                         |
| `Date Found`    | ISO 8601 timestamp                                                       |
| `Flagged`       | `YES` if the result is a directory, job board, news article, etc.      |
| `Flag Reason`   | Reason for the flag (`directory`, `pattern`, `geo-mismatch`, etc.) |

### Phase 2 enriched output adds

| Column              | Description                                                                  |
| ------------------- | ---------------------------------------------------------------------------- |
| `Email`           | Best contact email found (personal > priority generic > generic)             |
| `Phone`           | Best phone number found                                                      |
| `Lead Quality`    | `HOT` / `WARM` / `COLD` / `NOISE` — query-keyword relevance scoring |
| `Keyword Match %` | Percentage of query tokens found in page body text                           |

**Lead quality legend:**

| Grade     | Meaning                                                                               |
| --------- | ------------------------------------------------------------------------------------- |
| `HOT`   | ≥40% keyword match + contact or services signals — almost certainly a real prospect |
| `WARM`  | ≥20% keyword match or has About Us — plausibly relevant, worth reviewing            |
| `COLD`  | Some presence but low keyword overlap — tangentially relevant                        |
| `NOISE` | Job board, directory listing, or news article — skip                                 |

---

## Diagnose Your Engines

```bash
python diagnose.py              # test Mojeek, DDG, Yahoo (default)
python diagnose.py --bing       # test Bing (run with VPN/proxy active)
python diagnose.py --all        # test all 4 engines
python diagnose.py --no-wait    # skip inter-engine sleeps (quick dev check)
python diagnose.py -q "letting agents Birmingham"
```

Output shows: HTTP status, page size, selector match counts, sample URLs, geo-check results.

---

## Architecture Notes

**Why warmup runs inside the engine loop, not pre-flight:**
DDG Lite returns HTTP 202 (bot challenge) when the session is stale. In a naive pre-flight approach, Mojeek runs all queries (~12 s each × N queries + delays), and by the time DDG's turn comes the warmup session has expired. Moving warmup to immediately before each engine's first request ensures a ≤2 s gap regardless of how long the previous engine took.

**Why Yahoo needs dual-pattern selectors:**
Yahoo's HTML serves approximately 7 results with `div.compTitle > a[href]` and 3 results wrapped in an h3: `div.compTitle > h3 > a[href]`. A single selector misses 30% of results. Both patterns are combined in one CSS selector.

**Why Playwright is Pass 2 not Pass 1:**
Launching a headless browser for every site would take 3–5 s per site versus ~0.5 s for a plain HTTP GET. The vast majority of sites expose contact details in their static HTML. Playwright is reserved for the subset (~30–40%) that require JavaScript execution.

---

## Tech Stack

| Library | Role |
|---|---|
| `httpx[http2]` | Phase 1 — async HTTP/2 requests for search engine scraping |
| `beautifulsoup4` | Phase 1 — HTML parsing for search result extraction |
| `lxml` | Phase 1 — fast HTML/XML parser (beautifulsoup backend) |
| `playwright` | Phase 2 — headless Chromium fallback for JS-rendered sites |
| `requests` | Phase 2 — lightweight HTTP GET for contact enrichment pass |
| `openpyxl` | Excel output with colour-coded rows and Summary sheet |
| `pyyaml` | YAML config loading for Phase 2 settings |
| `tqdm` | Live terminal progress bar with ETA for both phases |
| `python-dotenv` | Optional — loads BING_PROXY from .env file |

---

## Project Structure

```
Leadhunter_Pro/
├── main.py                  ← Phase 1 orchestrator — scraping, dedup, CLI
├── enricher.py              ← Phase 2 orchestrator — two-pass enrichment pipeline
├── diagnose.py              ← Engine health checker
├── engine_base.py           ← Abstract base class for all search engine scrapers
├── config.py                ← Phase 1 settings (engines, delays, proxy)
├── config.yaml              ← Phase 2 settings (timeouts, paths, keywords)
├── config.example.yaml      ← Safe-to-commit placeholder template
├── queries.txt              ← One search query per line
├── queries.txt.example      ← Example queries file
├── engines/                 ← One module per search engine
│   ├── bing.py
│   ├── duckduckgo.py
│   ├── mojeek.py
│   └── yahoo.py
├── pipeline/                ← Shared data processing utilities
│   ├── data_cleaner.py      ← URL normalisation, domain dedup, ad/social filtering
│   ├── http_client.py       ← Threaded HTTP GET with hard timeout
│   ├── logger_setup.py      ← Rotating log file configuration
│   ├── output_writer.py     ← CSV/Excel output with colour-coded rows
│   └── query_manager.py     ← Query loading, dedup, progress tracking
├── core/                    ← Shared enrichment and contact extraction utilities
│   ├── _log.py              ← Internal logging helpers
│   ├── browser_utils.py     ← Playwright browser lifecycle and cookie dismissal
│   ├── controls.py          ← P/R/Q/S keyboard controls and command file polling
│   ├── email_utils.py       ← Email extraction, Cloudflare decoding, scoring
│   ├── http_utils.py        ← HTTP enrichment pass with fast-fail logic
│   ├── relevance.py         ← HOT/WARM/COLD/NOISE keyword scoring
│   └── storage.py           ← Atomic checkpoint, XLSX/CSV output
├── tests/                   ← pytest unit tests — no browser or internet required
│   ├── test_cleaner.py
│   ├── test_email_utils.py
│   ├── test_engines.py
│   └── test_relevance.py
├── outputs/                 ← leads_YYYY-MM-DD.csv / enriched_leads_YYYY-MM-DD.xlsx
├── assets/                  ← Screenshots for README
├── .github/
│   └── workflows/
│       └── ci.yml           ← CI pipeline
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── LICENSE                  ← MIT
└── README.md
```

---

## Requirements

- Python ≥ 3.10
- `pip install -r requirements.txt`
- `python -m playwright install chromium` (for Pass 2 enrichment)
- Bing: set `BING_PROXY` in `config.py` or use a VPN for reliable results

---

## Troubleshooting

**Bing returning results in wrong language or region:**
Set `BING_PROXY=http://user:pass@host:8080` in your `.env` file. `BING_PROXY` is read automatically at startup.

**DuckDuckGo returning HTTP 202 with no results:**
DDG's warmup mechanism is handled automatically. If persistent, increase `DELAY_BETWEEN_ENGINES` in `config.py` or pause for 10–15 minutes.

**One engine returning zero results consistently:**
Run `python diagnose.py` — it fires a test query at each engine and reports the HTTP status, result count, and error. Use it to identify which engine to temporarily disable in `ENGINES_PRIORITY` in `config.py`.

**Script stops mid-run:**
Checkpoint is saved every 50 queries. Re-run with the same `queries.txt` to resume from where it stopped.

---

## Part of the B2B Lead Toolkit

| Repo | What it does |
|---|---|
| **[Leadhunter Pro](https://github.com/FAAQJAVED/Leadhunter_Pro)** ← *you are here* | Multi-engine search scraper with HOT/WARM/COLD lead scoring |
| **[Email Phone Enrichment Tool](https://github.com/FAAQJAVED/Email-Phone-Number-Enrichment-Tool)** | Scrapes contact emails + phones from company websites |
| **[Google Maps Business Scraper](https://github.com/FAAQJAVED/Google-Maps-Business-Scraper)** | Extracts and enriches business listings from Google Maps |
| **[Trustpilot Business Scraper](https://github.com/FAAQJAVED/trustpilot-business-scraper)** | Extracts business listings from Trustpilot search results |
| **[JSON Directory Harvester](https://github.com/FAAQJAVED/json-directory-harvester)** | Configurable harvester for any JSON directory API with geo-filtering |

---

## License

MIT © 2026 [FAAQJAVED](https://github.com/FAAQJAVED) — see [LICENSE](LICENSE)
