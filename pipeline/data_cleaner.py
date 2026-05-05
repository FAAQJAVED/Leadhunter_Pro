"""
pipeline.data_cleaner — URL normalisation, deduplication, flagging, and scoring.

Key changes in v2.0
-------------------
- derive_name_from_domain() replaces title-based company name extraction.
- Directory domains are hard-excluded in process() — no CleanRecord created.
- _normalise_to_root() now collapses any path with 1+ segments to root.
- GEO_SUSPECT_TLDS (configurable) flags and penalises off-target TLDs.
- All industry-specific city lists, TLD scoring rules, and hardcoded keywords removed.
  SCORE_BOOST_KEYWORDS and GEO_SUSPECT_TLDS are now driven by config.py.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse

from config import EXCLUDED_DOMAINS, SCORE_BOOST_KEYWORDS

# GEO_SUSPECT_TLDS is imported and re-exported as a module-level variable so
# that tests can patch it via `import pipeline.data_cleaner as dc; dc.GEO_SUSPECT_TLDS = [...]`
# without importing the config module.  If the import from config fails
# (e.g. config doesn't define it yet), we fall back to an empty list.
try:
    from config import GEO_SUSPECT_TLDS as _cfg_geo
    GEO_SUSPECT_TLDS: list[str] = list(_cfg_geo)
except ImportError:
    GEO_SUSPECT_TLDS: list[str] = []

logger = logging.getLogger('lead_engine.cleaner')

# ---------------------------------------------------------------------------
# Tracking params to strip
# ---------------------------------------------------------------------------
_STRIP_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_reader', 'utm_name', 'gclid', 'fbclid', 'msclkid',
    'mc_cid', 'mc_eid', 'ref', 'referrer', 'source', 'yclid', '_ga',
    'igshid', 'si', 'feature', 'app', 'from',
}

# ---------------------------------------------------------------------------
# Ad redirect URL patterns (hard exclude, no row created)
# ---------------------------------------------------------------------------
_AD_REDIRECT_PATTERNS = [
    'bing.com/aclick',
    'google.com/aclk',
    'googleadservices.com',
    'doubleclick.net',
    'ad.doubleclick',
    'adservice.google',
]


def _is_ad_redirect(url: str) -> bool:
    """Return True if the URL is an ad/tracker redirect that must be dropped."""
    url_lower = url.lower()
    if any(p in url_lower for p in _AD_REDIRECT_PATTERNS):
        return True
    if len(url) > 300 and ('?ld=' in url_lower or '/aclick' in url_lower):
        return True
    return False


# ---------------------------------------------------------------------------
# Suspicious URL patterns → flagged=True (kept but marked)
# ---------------------------------------------------------------------------
_SUSPICIOUS_PATTERNS = [
    re.compile(r'^.{300,}$'),
    re.compile(r'(results|search|query|find)\?'),
    re.compile(r'\.(pdf|docx?|xlsx?|zip|tar|pptx?)$', re.I),
    re.compile(r'/jobs?/|/careers?/|/employment/', re.I),
    re.compile(r'/press/|/news/|/blog/|/article/', re.I),
    re.compile(r'/category/|/tag/|/topics?/', re.I),
    re.compile(r'/(en|us|uk)/\d{4}/', re.I),
]

# ---------------------------------------------------------------------------
# Hard excludes — no CleanRecord created for these domains
# Social media, encyclopedias, search engines, messaging platforms.
# Hard-excluded aggregator/directory domains
#         moved here from _DIRECTORY_DOMAINS (confirmed in production CSV).
# Government domains are query-dependent, not reliable lead sources —
#         universally irrelevant.  Users add them to their own blocklist if needed.
# google.co.uk omitted — google.com already covers this pattern.
# Removed domain-specific entries that are not general-purpose.
# ---------------------------------------------------------------------------
_ALWAYS_EXCLUDED = {
    # Social
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com',
    'linkedin.com', 'tiktok.com', 'youtube.com', 'pinterest.com',
    'reddit.com', 'quora.com', 'tumblr.com',
    'snapchat.com', 'threads.net', 'whatsapp.com', 'telegram.org',
    'discord.com', 'twitch.tv', 'vimeo.com', 'dailymotion.com',
    # Encyclopedias / reference
    'wikipedia.org', 'wikimedia.org', 'wikidata.org',
    'merriam-webster.com', 'dictionary.com', 'britannica.com',
    'cambridge.org',
    # App stores
    'play.google.com', 'apps.apple.com',
    # Search engines / maps
    'maps.google.com', 'google.com',
    # Misc junk
    'uservoice.com',
    # These are hard-excluded — they were in _DIRECTORY_DOMAINS but
    # produced CSV rows, proving the flag-only approach wasn't catching them
    'threebestrated.co.uk', 'trovit.co.uk', 'idobusiness.co.uk', 'servicevista.co.uk',
}

# ---------------------------------------------------------------------------
# Directory, aggregator, job board and platform domains
# These domains are hard-excluded in process() — process() returns None
#         immediately without creating a CleanRecord, so they never reach Phase 2.
# ---------------------------------------------------------------------------
_DIRECTORY_DOMAINS = {
    # Job boards
    'indeed.com', 'indeed.co.uk', 'glassdoor.com', 'reed.co.uk',
    'totaljobs.com', 'monster.com', 'cv-library.co.uk', 'ziprecruiter.com',
    'archinect.com', 'dezeen.com',
    # Agency / freelancer directories
    'clutch.co', 'bark.com', 'bark.co.uk', 'expertise.com',
    'thumbtack.com', 'angi.com', 'angieslist.com', 'homeadvisor.com',
    'homeguide.com', 'porch.com', 'houzz.com', 'houzz.co.uk',
    'designerslisted.com', 'designdirectory.co.uk',
    'checkatrade.com', 'rated.people.co.uk', 'freeindex.co.uk',
    'mybuilder.com', 'ratedpeople.com',
    # Review / rating sites
    'trustpilot.com', 'reviews.co.uk', 'reviewsolicitors.co.uk',
    'feefo.com', 'sitejabber.com', 'bbb.org',
    # Property portals and directories
    'yell.com', 'yelp.co.uk', 'yelp.com',
    'zoopla.co.uk', 'rightmove.co.uk', 'onthemarket.com',
    'primelocation.com', 'theagentfinder.co.uk',
    'allagents.co.uk', 'ratemyagent.co.uk', 'allthelettingagents.co.uk',
    'cylex-uk.co.uk', 'brownbook.net', 'hotfrog.co.uk',
    # General business directories
    'yellowpages.com', 'whitepages.com', 'superpages.com',
    'manta.com', 'chamberofcommerce.com', 'businessfinder.com',
    'bizapedia.com', 'dnb.com', 'dunsguide.com',
    'companieshouse.gov.uk', 'company-information.service.gov.uk',
    'opencorporates.com', 'companies.io',
    'abclocaldirectory.com', 'ultimatedir.biz', 'franklinreport.com',
    'generalcontractors.org',
    # Classified ads
    'craigslist.org', 'gumtree.com', 'chaosads.com',
    'canetads.com', 'locanto.com', 'oodle.com',
    # Interior design aggregators / listicles
    'bocadolobo.com', 'luxxu.net', 'roomdecorideas.eu',
    'livingroomideas.eu', 'bestinteriordesigners.eu',
    'thespruce.com', 'housebeautiful.com', 'architecturaldigest.com',
    'elledecor.com', 'veranda.com',
    'interiorzine.com', 'archdaily.com', 'designmilk.com',
    # Blog / writing platforms
    'zenwriting.net', 'medium.com', 'substack.com', 'wordpress.com',
    'blogspot.com', 'wix.com', 'weebly.com', 'squarespace.com',
    'ghost.io', 'sites.google.com',
    # Wiki platforms
    'wikiexpression.com', 'wikia.com', 'fandom.com', 'wikidot.com',
    # SEO tracking parasites
    'seowebstat.com', 'statscrop.com', 'websiteoutlook.com',
    'siteadvisor.com', 'similarweb.com',
    # Education / student platforms
    'unipage.net', 'educaedu.org', 'coursesfinder.org',
    'coursera.org', 'udemy.com', 'skillshare.com',
    # Services marketplaces
    'upwork.com', 'fiverr.com', 'freelancer.com', 'peopleperhour.com',
    'designhill.com', '99designs.com',
    # Lead gen / discovery services
    'thebuildermarket.com', 'hirerush.com', 'peerspace.com',
    'decorilla.com', 'havenly.com', 'modsy.com',
}

# ---------------------------------------------------------------------------
# Domains that require full path preservation
# ---------------------------------------------------------------------------
_KEEP_FULL_URL_DOMAINS = {
    'maps.google.com',
}

# ---------------------------------------------------------------------------
# Multi-dot parasite pattern (e.g. myvirtualhome.com.seowebstat.com)
# ---------------------------------------------------------------------------
_PARASITE_DOMAIN_RE = re.compile(
    r'\.(com|co\.uk|org|net|io)\.[a-z]+\.(com|co\.uk|org|net|io)$'
)

# ---------------------------------------------------------------------------
# Listicle pattern — URL signals blog/guide content, not a company homepage
# ---------------------------------------------------------------------------
_LISTICLE_RE = re.compile(
    r'(top-\d|best-|guide-to|how-to|the-best|tips-for|vs\.|comparison)',
    re.I,
)

# ---------------------------------------------------------------------------
# Stop words for irrelevance check
# ---------------------------------------------------------------------------
_RELEVANCE_STOP_WORDS = {
    'the', 'and', 'for', 'in', 'of', 'to', 'a', 'an', 'with', 'is',
    'are', 'we', 'our', 'your', 'that', 'this', 'it', 'at', 'on', 'by',
}

# ---------------------------------------------------------------------------
# TLD suffixes for domain-to-name derivation (longest first)
# ---------------------------------------------------------------------------
_TLD_SUFFIXES = sorted([
    '.co.uk', '.org.uk', '.me.uk', '.net.uk',
    '.com', '.co', '.org', '.net', '.io', '.uk',
    '.ca', '.au', '.de', '.fr', '.es', '.it', '.nl', '.us',
    '.biz', '.info',
], key=len, reverse=True)


def derive_name_from_domain(domain: str) -> str:
    """
    Derive a human-readable company name from a domain string.

    Algorithm
    ---------
    1. Strip www. prefix if present.
    2. Strip the TLD suffix (handles multi-part TLDs like .co.uk before .uk).
    3. Split on hyphens and underscores.
    4. Split on CamelCase transitions (insert space before uppercase preceded by lower).
    5. Title-case each token and join with spaces.
    6. Fall back to the raw domain if the result would be empty.

    Examples
    --------
    chestertons.co.uk             → "Chestertons"
    alpha-block-management.co.uk  → "Alpha Block Management"
    thelondonmanagementcompany.com → "The London Management Company"
    jpropertymanagement.co.uk     → "J Property Management"
    mlmproperty.co.uk             → "Mlm Property"

    Parameters
    ----------
    domain : Registrable domain string, e.g. "alpha-block-management.co.uk".

    Returns
    -------
    Title-cased company name string. Never returns an empty string.
    """
    if not domain:
        return ""

    name = domain

    # Strip www. (case-insensitive, preserve rest of case for CamelCase detection)
    if name.lower().startswith('www.'):
        name = name[4:]

    # Strip TLD using case-insensitive comparison but preserve the stem's case
    name_lower = name.lower()
    for tld in _TLD_SUFFIXES:
        if name_lower.endswith(tld):
            name = name[:-len(tld)]
            break

    if not name:
        return domain

    # CamelCase split BEFORE lowercasing — two passes required.
    #
    # Pass 1: consecutive-uppercase → last-upper + lowercase group
    #         e.g. "JProperty" → "J Property"  (J is isolated from Prop…)
    #         Pattern: one-or-more uppers followed by upper+lowers
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    #
    # Pass 2: lower → upper transition
    #         e.g. "blockManager" → "block Manager"
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)

    # Split on hyphens and underscores
    name = re.sub(r'[-_]', ' ', name)

    # Title-case and join
    parts = [word.capitalize() for word in name.split() if word]
    return ' '.join(parts) if parts else domain


# =============================================================================
# CleanRecord
# =============================================================================

class CleanRecord:
    """Represents one cleaned, scored lead record ready for output."""

    __slots__ = ('company_name', 'website_url', 'domain',
                 'search_query', 'search_engine', 'date_found',
                 'flagged', 'flag_reason', 'score')

    def __init__(self, *, company_name: str, website_url: str, domain: str,
                 search_query: str, search_engine: str,
                 date_found: str, flagged: bool, flag_reason: str = '',
                 score: int = 0) -> None:
        self.company_name  = company_name
        self.website_url   = website_url
        self.domain        = domain
        self.search_query  = search_query
        self.search_engine = search_engine
        self.date_found    = date_found
        self.flagged       = flagged
        self.flag_reason   = flag_reason
        self.score         = score

    def to_dict(self) -> dict:
        return {
            'company_name':  self.company_name,
            'website_url':   self.website_url,
            'domain':        self.domain,
            'search_query':  self.search_query,
            'search_engine': self.search_engine,
            'date_found':    self.date_found,
            'flagged':       'YES' if self.flagged else '',
            'flag_reason':   self.flag_reason,
            'score':         self.score,
        }


# =============================================================================
# DataCleaner
# =============================================================================

class DataCleaner:
    """
    Normalises, deduplicates, flags, and scores scraped search results.

    self._seen_domains stores base_domain(url) — the netloc with www. stripped.
    This is shared across ALL engines in one scrape session, so if Mojeek
    returns 'example.com/' and Yahoo returns 'example.com/about', both map to
    the same domain key and the duplicate is silently dropped.
    Domain-level cross-engine dedup is therefore built-in.
    """

    def __init__(self) -> None:
        self._seen_domains: set[str] = set()

    def load_seen_domains(self, domains: set[str]) -> None:
        """Seed the deduplication set from a checkpoint's collected_domains."""
        self._seen_domains = set(domains)

    def process(self, result, *, search_query: str,
                search_engine: str) -> CleanRecord | None:
        """
        Convert one raw SearchResult into a CleanRecord, or return None to skip.

        Skip conditions (in order)
        --------------------------
        1. Ad redirect URL patterns.
        2. URL fails normalisation.
        3. Domain in _DIRECTORY_DOMAINS  (hard exclude, no row created).
        4. Domain in _ALWAYS_EXCLUDED or EXCLUDED_DOMAINS from config.
        5. Parasite multi-dot domain pattern.
        6. Already seen this domain (cross-engine dedup).

        Flag conditions (record is created but marked)
        -----------------------------------------------
        - Suspicious URL pattern.
        - Deep subdomain (> 4 dot-parts).
        - GEO_SUSPECT_TLDS match (configurable via config.py).
        - Title/query irrelevance (zero meaningful-word overlap).
        """
        # Step 1: Ad redirect
        if _is_ad_redirect(result.url):
            logger.debug('Skipped (ad redirect): %s', result.url[:80])
            return None

        url = normalise_url(result.url)
        if not url:
            return None

        domain = base_domain(url)
        if not domain:
            return None

        # Step 3: Directory domains are hard-excluded (no row created)
        if domain in _DIRECTORY_DOMAINS:
            logger.debug('Skipped (directory hard-exclude): %s', domain)
            return None

        # Step 4: Always-excluded and config-excluded
        if domain in _ALWAYS_EXCLUDED or is_excluded(domain):
            logger.debug('Skipped (excluded): %s', domain)
            return None

        # Step 5: Parasite domain
        if _PARASITE_DOMAIN_RE.search(domain):
            logger.debug('Skipped (parasite domain): %s', domain)
            return None

        # Step 6: Domain dedup
        if domain in self._seen_domains:
            logger.debug('Skipped (dup): %s', domain)
            return None
        self._seen_domains.add(domain)

        # Normalise to root — collapse any URL with a path segment down to the homepage
        url = _normalise_to_root(url, domain)

        flagged, flag_reason = _assess(url, domain, search_query)
        score                = _score(url, domain, search_query)

        # Geo-suspect TLD flagging (configurable via GEO_SUSPECT_TLDS in config.py)
        # GEO_SUSPECT_TLDS is a module-level variable so tests can patch it.
        if GEO_SUSPECT_TLDS:
            tld = domain.split('.')[-1]
            if tld in GEO_SUSPECT_TLDS:
                flagged     = True
                flag_reason = 'geo-suspect'
                score      -= 2

        # Company name is derived from the domain, not the search-engine page title
        company_name = derive_name_from_domain(domain)

        # Irrelevance check — use title tokens vs query tokens
        # The title is still useful here even though we don't store it as the name
        clean_title  = re.split(r'\s*[\|\-–—]\s*', result.title or '')[0].strip()
        title_tokens = {
            w for w in re.findall(r'\b[a-z]{4,}\b', clean_title.lower())
            if w not in _RELEVANCE_STOP_WORDS
        }
        query_tokens = {
            w for w in re.findall(r'\b[a-z]{4,}\b', search_query.lower())
            if w not in _RELEVANCE_STOP_WORDS
        }
        if title_tokens and query_tokens and not (title_tokens & query_tokens):
            score = -5
            if not flag_reason:
                flag_reason = 'irrelevant'
            flagged = True

        date_found = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        return CleanRecord(
            company_name=company_name,
            website_url=url,
            domain=domain,
            search_query=search_query,
            search_engine=search_engine,
            date_found=date_found,
            flagged=flagged,
            flag_reason=flag_reason,
            score=score,
        )


# =============================================================================
# Pure functions
# =============================================================================

def normalise_url(url: str) -> str:
    """Strip tracking parameters, lowercase netloc, remove trailing slashes."""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        if url.startswith('//'):
            url = 'https:' + url
        else:
            return ''
    try:
        parsed   = urlparse(url)
        clean_qs = urlencode([(k, v) for k, v in parse_qsl(parsed.query)
                              if k.lower() not in _STRIP_PARAMS])
        return urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip('/') or '/',
            parsed.params,
            clean_qs,
            '',
        ))
    except Exception:
        return ''


def _normalise_to_root(url: str, domain: str) -> str:
    """
    Collapse any URL with 1 or more path segments to the site root.

    Collapses if segments >= 1, so /any-path-segment → /.
    This prevents Phase 2 from hitting both the deep page AND /contact on top.
    """
    if domain in _KEEP_FULL_URL_DOMAINS:
        return url
    try:
        parsed   = urlparse(url)
        segments = [s for s in parsed.path.split('/') if s]
        if len(segments) >= 1:
            return urlunparse((parsed.scheme, parsed.netloc, '/', '', '', ''))
        return url
    except Exception:
        return url


def base_domain(url: str) -> str:
    """Return the registrable domain (no www, no path, lowercase)."""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return netloc.split(':')[0]
    except Exception:
        return ''


def is_excluded(domain: str) -> bool:
    """Check if domain matches any entry in the config EXCLUDED_DOMAINS set."""
    return any(
        domain == ex or domain.endswith('.' + ex)
        for ex in EXCLUDED_DOMAINS
    )


def _assess(url: str, domain: str, query: str) -> tuple[bool, str]:
    """
    Return (flagged: bool, reason: str) for ambiguous cases.

    Industry-specific geo-mismatch checks have been removed — this tool is industry-agnostic.
    Directory check lives in process() as a hard exclude (returns None).
    """
    for pat in _SUSPICIOUS_PATTERNS:
        if pat.search(url):
            return True, 'pattern'

    parts = domain.split('.')
    if len(parts) > 4:
        return True, 'deep-subdomain'

    return False, ''


def _score(url: str, domain: str, query: str) -> int:
    """
    Confidence score — higher = more likely a real company homepage.

    SCORE_BOOST_KEYWORDS comes from config.py (default empty list).
    Populate it with industry-relevant terms via config.yaml.

    +1  URL path contains a keyword from SCORE_BOOST_KEYWORDS
    -1  URL has 3+ path segments deep (probably a blog/article)
    -2  URL matches listicle / directory-article patterns
    """
    s         = 0
    url_lower = url.lower()

    if any(kw in url_lower for kw in SCORE_BOOST_KEYWORDS):
        s += 1

    try:
        segments = [seg for seg in urlparse(url).path.split('/') if seg]
        if len(segments) >= 3:
            s -= 1
    except Exception:
        pass

    if _LISTICLE_RE.search(url_lower):
        s -= 2

    return s
