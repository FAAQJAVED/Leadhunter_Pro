# 🔍 LeadHunter Pro

> **Multi-engine search scraper + contact enricher** — searches four independent engines simultaneously, extracts emails & phones from every result, and scores every lead as HOT, WARM, COLD, or NOISE. Final output is a colour-coded Excel spreadsheet, ready to use.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/FAAQJAVED/Leadhunter_Pro/actions/workflows/ci.yml/badge.svg)](https://github.com/FAAQJAVED/Leadhunter_Pro/actions)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/FAAQJAVED/Leadhunter_Pro)

---

## What it does

- **Searches 4 independent engines at once** — Mojeek, DuckDuckGo, Yahoo, and Bing — combining and deduplicating all results automatically
- **Pass 1 (HTTP):** fires lightweight `requests` GET calls at every discovered homepage and contact sub-pages, extracting plaintext and Cloudflare-obfuscated emails + phone numbers
- **Pass 2 (Browser):** runs headless Chromium via Playwright on every site Pass 1 missed — handles JavaScript-rendered pages, SPAs, and React / Next.js frontends
- **Scores every lead** as `HOT`, `WARM`, `COLD`, or `NOISE` using query-keyword matching against the full page body
- **Outputs** a score-sorted, hyperlinked, colour-coded Excel workbook with HOT/WARM/COLD badges and a Summary sheet, plus a CSV backup

---

## Key Features

| Feature | Detail |
|---|---|
| **4 search engines** | Mojeek, DuckDuckGo, Yahoo, Bing — independent indexes, combined deduplication |
| **Per-engine session warmup** | Runs immediately before each engine's first request (≤2 s gap) — prevents HTTP 202 bot challenges |
| **Dual-pattern Yahoo selector** | Pattern A (`div.compTitle > a`) + Pattern B (`div.compTitle > h3 > a`) — catches all 10 results |
| **Cloudflare email decoding** | XOR-decodes `cdn-cgi/l/email-protection` and `data-cfemail` attributes |
| **Two-pass enrichment** | Pass 1: fast HTTP GET · Pass 2: Playwright headless Chromium fallback for JS-rendered sites |
| **Email quality scoring** | Personal name = best (1), priority generic (2), generic (3), junk filtered (999) |
| **Lead quality scoring** | HOT / WARM / COLD / NOISE — query-keyword matching, works for any industry |
| **Live keyboard controls** | `P` pause · `R` resume · `Q` quit · `S` status · `W` hand off to Phase 2 |
| **Crash-safe checkpointing** | Atomic writes (`os.replace`) — resume from any interruption with zero data loss |
| **Internet auto-pause** | Detects connectivity loss, pauses, and auto-resumes when connection returns |
| **Background auto-save** | Saves every 60 s in addition to per-site saves |
| **Universal Phase 1 filters** | Ad redirect URLs · extended social platforms · structural garbage (score −5) |
| **Formatted Excel output** | Score-sorted, hyperlinked, colour-coded + HOT/WARM/COLD badges + Summary sheet |

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

## Real Results

> Tested against UK property-sector queries targeting letting agents, block managers, and HMO landlords across multiple cities.

- **~80% contact hit rate** across both passes — most company sites expose emails in static HTML
- **Additional ~10–15%** recovered by Pass 2 (Playwright) on JS-heavy portals
- **Cloudflare-protected sites** decoded correctly — XOR key is extracted and applied per address
- **All 4 engines** running concurrently yield 3–4× more unique domains than any single engine alone

### Phase 1 — Scraping in progress

![Phase 1 scraping in progress](assets/phase1-scraping.png)

### Phase 2 — Enrichment running

![Phase 2 enrichment running](assets/phase2-enrichment.png)

### Excel output

![Colour-coded Excel output](assets/excel-output-sample.png)

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/FAAQJAVED/Leadhunter_Pro.git
cd leadhunter-pro
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright Chromium

```bash
python -m playwright install chromium
```

### 4. Add your queries

```bash
cp queries.txt.example queries.txt
# Edit queries.txt — one search term per line
```

### 5. Check engines are healthy

```bash
python diagnose.py
```

### 6. Run

```bash
# Runs Phase 1 (scraping), then prompts for Phase 2 (enrichment)
python main.py
```

---

## Or Run Phases Separately

```bash
# Phase 1 only — specific engines, specific query
python main.py --query "letting agents Manchester" --mojeek --ddg

# Phase 2 only — enrich an existing CSV
python enricher.py --input outputs/leads_2026-05-01.csv
```

---

## Output Format

### Phase 1 output columns

| Column | Description |
|---|---|
| `Score` | Confidence score (higher = more likely a real company homepage) |
| `Company Name` | Cleaned page title (URL bleeding and breadcrumbs stripped) |
| `Website URL` | Normalised homepage URL (tracking params removed) |
| `Domain` | Base domain (cross-engine dedup key) |
| `Search Query` | The query that found this result |
| `Search Engine` | Engine that returned this result |
| `Date Found` | ISO 8601 timestamp |
| `Flagged` | `YES` if the result is a directory, job board, news article, etc. |
| `Flag Reason` | Reason for the flag (`directory`, `pattern`, `geo-mismatch`, etc.) |

### Phase 2 enriched output adds

| Column | Description |
|---|---|
| `Email` | Best contact email found (personal > priority generic > generic) |
| `Phone` | Best phone number found |
| `Lead Quality` | `HOT` / `WARM` / `COLD` / `NOISE` — query-keyword relevance scoring |
| `Keyword Match %` | Percentage of query tokens found in page body text |

### Lead quality legend

| Grade | Meaning |
|---|---|
| `HOT` | ≥40% keyword match + contact or services signals — almost certainly a real prospect |
| `WARM` | ≥20% keyword match or has About Us — plausibly relevant, worth reviewing |
| `COLD` | Some presence but low keyword overlap — tangentially relevant |
| `NOISE` | Job board, directory listing, or news article — skip |

---

## Runtime Controls

| Key | Phase | Action |
|---|---|---|
| `P` | 1 & 2 | Pause / resume toggle |
| `R` | 1 & 2 | Resume if paused |
| `Q` | 1 & 2 | Quit and save progress |
| `S` | 1 & 2 | Print current status |
| `W` | 1 | End Phase 1 early, go directly to Phase 2 prompt |

> **Windows:** single keypress — no Enter required (uses `msvcrt`).  
> **Mac / Linux:** type the letter then press **Enter** (uses `select` + stdin).

**Remote control via file** (works while the script is running in a terminal or scheduled task):

```bash
echo pause   > command.txt   # pause after current site
echo resume  > command.txt   # resume
echo stop    > command.txt   # save and exit
echo fresh   > command.txt   # delete checkpoint (restart on next run)
```

---

## Configuration

### `config.py` — Phase 1 (scraper) settings

| Setting | Default | Description |
|---|---|---|
| `ENGINES_PRIORITY` | `['mojeek','duckduckgo','yahoo','bing']` | Engine order |
| `PAGES_PER_QUERY` | `5` | Result pages per query per engine |
| `BING_PROXY` | `''` | Residential proxy URL for Bing geo-unlock |
| `DELAY_BETWEEN_REQUESTS` | `(3, 8)` | Seconds between HTTP requests |
| `DELAY_BETWEEN_QUERIES` | `(20, 45)` | Seconds between queries |
| `DELAY_BETWEEN_ENGINES` | `(60, 120)` | Seconds between engine switches |

### `config.yaml` — Phase 2 (enricher) settings

Copy the example file to get started:

```bash
cp config.example.yaml config.yaml
```

Key settings: `http_timeout`, `playwright_timeout`, `stop_at`, `contact_paths`, `skip_email_keywords`.

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

![Diagnose terminal output](assets/diagnose-output.png)

---

## Project Structure

```
leadhunter-pro/
├── main.py                  ← Phase 1 orchestrator — scraping, dedup, CLI
├── enricher.py              ← Phase 2 orchestrator — two-pass enrichment pipeline
├── diagnose.py              ← Engine health checker
├── data_cleaner.py          ← URL normalisation, domain dedup, ad/social filtering
├── config.py                ← Phase 1 settings (engines, delays, proxy)
├── config.yaml              ← Phase 2 settings (timeouts, paths, keywords)
├── config.example.yaml      ← Safe-to-commit placeholder template
├── queries.txt              ← One search query per line
├── queries.txt.example      ← Example queries file
├── outputs/                 ← leads_YYYY-MM-DD.csv / enriched_leads_YYYY-MM-DD.xlsx
├── assets/                  ← Screenshots for README
├── .github/
│   └── workflows/
│       └── ci.yml           ← CI pipeline
├── requirements.txt
├── LICENSE                  ← MIT
└── README.md
```

---

## Troubleshooting — Geo-Blocks & Empty Results

Run a health check first:

```bash
python diagnose.py --all
```

If an engine shows 0 results or a non-200 status, it is being blocked.

| Symptom | Likely Cause | Fix |
|---|---|---|
| `HTTP 202` on DuckDuckGo | Bot challenge — session too old | Wait 5–10 min and retry; warmup will re-establish the session |
| `HTTP 403` or `HTTP 429` | Rate limited | Increase `DELAY_BETWEEN_REQUESTS` and `DELAY_BETWEEN_ENGINES` in `config.py` |
| Bing returns 0 results | Geo-block (Bing blocks residential IPs outside US/UK) | Use a residential proxy — see below |
| Yahoo results in wrong language | Geo-mismatch | Use a UK/US VPN before running |
| `SSL` / `ConnectionError` | Network instability | The tool auto-pauses and retries — check your connection |
| Results are all directories/portals | Normal on page 1 | Run more pages (`--pages 10`) or add terms to `SCORE_BOOST_KEYWORDS` |

### Using a proxy for Bing

**Option A — `.env` file (recommended):**
```bash
BING_PROXY=http://user:pass@your-proxy-host:8080
```

**Option B — `config.py` directly:**
```python
BING_PROXY = 'http://user:pass@your-proxy-host:8080'   # HTTP proxy
BING_PROXY = 'socks5://user:pass@your-proxy-host:1080' # SOCKS5 proxy
```

Leave `BING_PROXY` empty to skip Bing and run only the other three engines — they work well on most residential connections without a proxy.

### Increasing delays to avoid rate-limiting

```python
DELAY_BETWEEN_REQUESTS = (8, 15)   # seconds between individual HTTP requests (default 3–8)
DELAY_BETWEEN_QUERIES  = (30, 60)  # seconds between queries (default 20–45)
DELAY_BETWEEN_ENGINES  = (90, 150) # seconds between engines (default 60–120)
```

---

## Part of the B2B Lead Toolkit

LeadHunter Pro is one component of a broader B2B lead generation pipeline targeting UK property management companies, letting agents, block managers, and HMO landlords.

| Repo | What it does |
|---|---|
| **[Leadhunter_Pro](https://github.com/FAAQJAVED/Leadhunter_Pro)** ← *you are here* | Scrapes 4 search engines to find verified company websites, scores and deduplicates results |
| **[Email-Phone-Number-Enrichment-Tool](https://github.com/FAAQJAVED/Email-Phone-Number-Enrichment-Tool)** | Scrapes contact emails + phones from company websites |
| **[google-maps-scraper](https://github.com/FAAQJAVED/google-maps-scraper)** | Extracts business listings (name, address, phone, website) from Google Maps |

---

## Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)
![Requests](https://img.shields.io/badge/Requests-FF6B35?style=for-the-badge)
![OpenPyXL](https://img.shields.io/badge/OpenPyXL-217346?style=for-the-badge&logo=microsoft-excel&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)

| Library | Role |
|---|---|
| `requests` | Pass 1 — fast, lightweight HTTP GET with threading-based hard timeout |
| `playwright` | Pass 2 — headless Chromium for JavaScript-rendered pages |
| `beautifulsoup4` | HTML parsing — title extraction, link crawling, contact page discovery |
| `openpyxl` | Excel output with colour-coded rows, hyperlinks, and Summary sheet |
| `pyyaml` | YAML config loading with default fallback for Phase 2 |
| `tqdm` | Live terminal progress bar with ETA for both passes |

---

## Notes

- `robots.txt` is **not** enforced automatically — ensure your use case complies with each site's terms of service and applicable law.
- SSL certificate errors are suppressed to handle sites with expired or self-signed certificates.
- No data is stored or transmitted externally — all output is written locally.
- Bing's geo-blocking behaviour varies by IP and region — always run `diagnose.py` first if Bing results seem empty.

---

## Requirements

- Python ≥ 3.10
- `pip install -r requirements.txt`
- `python -m playwright install chromium` (for Pass 2 enrichment)
- Bing: set `BING_PROXY` in `config.py` or `.env`, or use a VPN for reliable results

---

## License

MIT © 2024 [FAAQJAVED](https://github.com/FAAQJAVED)
