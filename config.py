# config.py — LeadHunter Pro: All Tuneable Settings

import os
from os import path as os_path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

ENGINES_PRIORITY = ['mojeek', 'duckduckgo', 'yahoo', 'bing']
PAGES_PER_QUERY  = 5

BING_PROXY = os.getenv('BING_PROXY', '')  # set in .env or environment; e.g. 'http://user:pass@host:8080'

DELAY_BETWEEN_REQUESTS = (3, 8)
DELAY_BETWEEN_PAGES    = (8, 15)
DELAY_BETWEEN_QUERIES  = (20, 45)
DELAY_BETWEEN_ENGINES  = (60, 120)

CONNECT_TIMEOUT  = 10
READ_TIMEOUT     = 30
FOLLOW_REDIRECTS = True
HTTP2_ENABLED    = True
MAX_RETRIES      = 4

COOLDOWN_ON_429       = 600
MAX_CONSECUTIVE_429S  = 3

# Updated to Chrome 131-136 (Nov 2024 – Apr 2026).
# Stale User-Agents (120-124, released Apr 2024) are a primary bot-detection
# signal — Yahoo and Mojeek both check UA recency against known release dates.
USER_AGENTS = [
    # Chrome 131–136 (Windows) — Nov 2024 – Apr 2026
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    # Chrome + Edge 131–136 (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    # Firefox 128–135 (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    # Chrome 131–135 (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]

EXCLUDED_DOMAINS = {
    'facebook.com', 'linkedin.com', 'twitter.com', 'x.com',
    'instagram.com', 'youtube.com', 'wikipedia.org', 'tiktok.com',
}

GEO_SUSPECT_TLDS: list[str] = []
SCORE_BOOST_KEYWORDS: list[str] = []

_base = os_path.dirname(os_path.abspath(__file__))
OUTPUT_DIR     = os_path.join(_base, 'outputs')
LOG_DIR        = os_path.join(_base, 'logs')
CHECKPOINT_DIR = os_path.join(_base, 'checkpoints')

CHECKPOINT_EVERY = 50
CHECKPOINT_FILE  = os_path.join(CHECKPOINT_DIR, 'checkpoint.json')

BEEP_COMPLETE = (1000, 500)
BEEP_ERROR    = (500, 1000)
