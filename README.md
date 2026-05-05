Readme · MDCopyLeadHunter Pro
Multi-engine search scraper + contact enricher. Finds business leads, extracts emails & phones, scores lead quality.
Show Image
Show Image
Show Image
Show Image

What It Does
LeadHunter Pro searches four independent search engines simultaneously to find real business websites matching your query. It then visits each website to extract a contact email address and phone number, and scores every lead as HOT, WARM, COLD, or NOISE based on how closely the page content matches what you searched for. The final output is a colour-coded Excel spreadsheet, ready to use.

Preview

Add your screenshots to the assets/ folder and they will appear here automatically.
See assets/README.md for the recommended screenshot guide.

Phase 1 — ScrapingPhase 2 — EnrichmentShow ImageShow Image
Excel OutputDiagnose OutputShow ImageShow Image

How It Works
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

Features
FeatureDetail4 search enginesMojeek, DuckDuckGo, Yahoo, Bing — independent indexes, combined deduplicationPer-engine session warmupRuns immediately before each engine's first request (≤2 s gap) — prevents HTTP 202 bot challengesDual-pattern Yahoo selectorPattern A (div.compTitle > a) + Pattern B (div.compTitle > h3 > a) — catches all 10 resultsCloudflare email decodingXOR-decodes cdn-cgi/l/email-protection and data-cfemail attributesTwo-pass enrichmentPass 1: fast HTTP GET · Pass 2: Playwright headless Chromium fallback for JS-rendered sitesEmail scoringPersonal name = best (1), priority generic (2), generic (3), junk filtered (999)Lead quality scoringHOT / WARM / COLD / NOISE — query-keyword matching, works for any industryLive keyboard controlsP pause · R resume · Q quit · S status · W hand off to Phase 2Crash-safe checkpointingAtomic writes (os.replace) — resume from any interruption with zero data lossInternet auto-pauseDetects connectivity loss, pauses, and auto-resumes when connection returnsBackground auto-saveSaves every 60 s in addition to per-site savesUniversal Phase 1 filtersAd redirect URLs · extended social platforms · structural garbage (score −5)Formatted Excel outputScore-sorted, hyperlinked, colour-coded + HOT/WARM/COLD badges + Summary sheet

Quick Start
bashgit clone https://github.com/FAAQJAVED/Leadhunter_Pro.git
cd leadhunter-pro
pip install -r requirements.txt
python -m playwright install chromium

# Add your queries (one per line)
cp queries.txt.example queries.txt
# Edit queries.txt with your search terms

# Check engines are healthy first
python diagnose.py

# Run Phase 1 (scraping) — prompted for Phase 2 (enrichment) at the end
python main.py

Or Run Phases Separately
bash# Phase 1 only — specific engines, specific query
python main.py --query "letting agents Manchester" --mojeek --ddg

# Phase 2 only — enrich an existing CSV
python enricher.py --input outputs/leads_2026-05-01.csv

Configuration
config.py — Phase 1 (scraper) settings
SettingDefaultDescriptionENGINES_PRIORITY['mojeek','duckduckgo','yahoo','bing']Engine orderPAGES_PER_QUERY5Result pages per query per engineBING_PROXY''Residential proxy URL for Bing geo-unlock. Format: http://user:pass@host:portDELAY_BETWEEN_REQUESTS(3, 8)Seconds between HTTP requestsDELAY_BETWEEN_QUERIES(20, 45)Seconds between queriesDELAY_BETWEEN_ENGINES(60, 120)Seconds between engine switches
Bing proxy options:
python# Authenticated residential proxy
BING_PROXY = 'http://user:pass@uk.residential.proxy:8080'

# SOCKS5
BING_PROXY = 'socks5://user:pass@proxy-host:1080'
config.yaml — Phase 2 (enricher) settings
bashcp config.example.yaml config.yaml
Key settings: http_timeout, playwright_timeout, stop_at, contact_paths, skip_email_keywords.

Runtime Controls
KeyPhaseActionP1 & 2Pause / resume toggleR1 & 2Resume if pausedQ1 & 2Quit and save progressS1 & 2Print current statusW1End Phase 1 early, go directly to Phase 2 prompt
Windows: single key, no Enter required
Mac / Linux: type the letter then press Enter
Automation: write a command to command.txt (pause, resume, stop, fresh) — useful for scripting.

Output Format
Phase 1 output columns
ColumnDescriptionScoreConfidence score (higher = more likely a real company homepage)Company NameCleaned page title (URL bleeding and breadcrumbs stripped)Website URLNormalised homepage URL (tracking params removed)DomainBase domain (cross-engine dedup key)Search QueryThe query that found this resultSearch EngineEngine that returned this resultDate FoundISO 8601 timestampFlaggedYES if the result is a directory, job board, news article, etc.Flag ReasonReason for the flag (directory, pattern, geo-mismatch, etc.)
Phase 2 enriched output adds
ColumnDescriptionEmailBest contact email found (personal > priority generic > generic)PhoneBest phone number foundLead QualityHOT / WARM / COLD / NOISE — query-keyword relevance scoringKeyword Match %Percentage of query tokens found in page body text
Lead quality legend:
GradeMeaningHOT≥40% keyword match + contact or services signals — almost certainly a real prospectWARM≥20% keyword match or has About Us — plausibly relevant, worth reviewingCOLDSome presence but low keyword overlap — tangentially relevantNOISEJob board, directory listing, or news article — skip

Diagnose Your Engines
bashpython diagnose.py              # test Mojeek, DDG, Yahoo (default)
python diagnose.py --bing       # test Bing (run with VPN/proxy active)
python diagnose.py --all        # test all 4 engines
python diagnose.py --no-wait    # skip inter-engine sleeps (quick dev check)
python diagnose.py -q "letting agents Birmingham"
Output shows: HTTP status, page size, selector match counts, sample URLs, geo-check results.

Architecture Notes
Why warmup runs inside the engine loop, not pre-flight:
DDG Lite returns HTTP 202 (bot challenge) when the session is stale. In a naive pre-flight approach, Mojeek runs all queries (~12 s each × N queries + delays), and by the time DDG's turn comes the warmup session has expired. Moving warmup to immediately before each engine's first request ensures a ≤2 s gap regardless of how long the previous engine took.
Why Yahoo needs dual-pattern selectors:
Yahoo's HTML serves approximately 7 results with div.compTitle > a[href] and 3 results wrapped in an h3: div.compTitle > h3 > a[href]. A single selector misses 30% of results. Both patterns are combined in one CSS selector.
Why Playwright is Pass 2 not Pass 1:
Launching a headless browser for every site would take 3–5 s per site versus ~0.5 s for a plain HTTP GET. The vast majority of sites expose contact details in their static HTML. Playwright is reserved for the subset (~30–40%) that require JavaScript execution.

Part of the B2B Lead Toolkit
This scraper is one component of a broader B2B lead generation pipeline targeting UK property management companies, letting agents, block managers, and HMO landlords.
RepoWhat it doesLeadhunter_Pro ← you are hereScrapes 4 search engines to find verified company websites, scores and deduplicates resultsEmail-Phone-Number-Enrichment-ToolScrapes contact emails + phones from company websitesgoogle-maps-scraperExtracts business listings (name, address, phone, website) from Google Maps

Requirements

Python ≥ 3.10
pip install -r requirements.txt
python -m playwright install chromium (for Pass 2 enrichment)
Bing: set BING_PROXY in config.py or use a VPN for reliable results


Troubleshooting — Errors, Geo-Blocks & Empty Results
If engines return no results, return HTTP 202 / 403, or the tool stops early, it is almost always a geo-block or rate-limit. Here is what to do.
Quick checks first
bashpython diagnose.py --all    # confirms which engines are healthy right now
If an engine shows 0 results or a non-200 status in diagnose output, it is being blocked.

Common errors and fixes
SymptomLikely CauseFixHTTP 202 on DuckDuckGoBot challenge — session too oldWait 5–10 min and retry; the warmup will re-establish the sessionHTTP 403 or HTTP 429Rate limitedIncrease DELAY_BETWEEN_REQUESTS and DELAY_BETWEEN_ENGINES in config.pyBing returns 0 resultsGeo-block (Bing blocks residential IPs outside the US/UK)Use a residential proxy — see belowYahoo results in wrong languageGeo-mismatchUse a UK/US VPN before runningSSL / ConnectionErrorNetwork instabilityThe tool will auto-pause and retry — check your connectionResults are all directories/portalsNormal on page 1 — they dominate early resultsRun more pages (--pages 10) or add terms to SCORE_BOOST_KEYWORDS in config.py

Using a VPN (quickest fix for general use)

Connect your VPN to a UK or US server before running the tool.
Run python diagnose.py --all to confirm all engines pass.
Run normally. No config changes needed — the tool will use your VPN tunnel automatically.


Recommended for: Bing, Yahoo, and any engine showing geo-blocked results.
Free VPN options: ProtonVPN free tier (UK server), Windscribe free tier.


Using a proxy for Bing specifically
Bing is the most aggressively geo-blocked engine. If you have a residential proxy, configure it in .env (preferred) or config.py:
Option A — .env file (recommended, keeps credentials out of code):
bash# .env
BING_PROXY=http://user:pass@your-proxy-host:8080
Option B — config.py directly:
pythonBING_PROXY = 'http://user:pass@your-proxy-host:8080'   # HTTP proxy
BING_PROXY = 'socks5://user:pass@your-proxy-host:1080' # SOCKS5 proxy
Leave BING_PROXY empty to skip Bing entirely and run only the other three engines — they work well without a proxy on most residential connections.

Increasing delays to avoid rate-limiting
If you are hitting limits frequently, edit config.py:
pythonDELAY_BETWEEN_REQUESTS = (8, 15)   # seconds between individual HTTP requests (default 3–8)
DELAY_BETWEEN_QUERIES  = (30, 60)  # seconds between queries (default 20–45)
DELAY_BETWEEN_ENGINES  = (90, 150) # seconds between engines (default 60–120)
The tool will still run — it just paces itself more cautiously.

License
MIT — see LICENSE
