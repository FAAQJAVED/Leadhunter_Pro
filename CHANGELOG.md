# Changelog

## v1.1.3 — 2026-06-18

### Bug Fixes

* **Yahoo engine** – switched transport from `httpx` to `curl_cffi` (Chrome TLS
  impersonation). `httpx` was returning HTTP 500 on every Yahoo request
  regardless of header configuration or the two-step warmup; the underlying
  cause is a TLS/JA3 fingerprint check, not a missing header or session
  cookie — `httpx`/`requests` use Python's stdlib `ssl` module, which
  produces a non-browser TLS ClientHello identifiable before any HTTP
  header is read. `curl_cffi` wraps libcurl + BoringSSL to replicate a
  genuine Chrome TLS handshake and succeeds on a single cold GET — no
  warmup, no cookies, no Referer required.
* **Main scraper** – removed the now-dead two-step Yahoo warmup
  (`yahoo.com` → `search.yahoo.com`, 500-retry-with-cooldown) from
  `_do_engine_warmup()`. Yahoo's `_do_engine_warmup` branch is now a no-op
  that returns `True` immediately; `engines/yahoo.py` manages its own
  `curl_cffi` client and requires no session preparation.
* **Diagnose** – `diagnose.py`'s Yahoo test path now uses `curl_cffi`
  (mirroring the production engine exactly) instead of the old `httpx`
  two-step warmup, so the diagnostic accurately reflects real engine
  behaviour. `warmup_needed` for Yahoo changed from `True` to `False`.

### New files

* `pipeline/curl_client.py` – lightweight `curl_cffi`-backed client
  (`CurlCffiClient`) matching `HttpClient`'s public interface
  (`get`/`post` → `Response(http, html)`), used exclusively by
  `engines/yahoo.py`. Mojeek, Bing, and DuckDuckGo are unaffected and
  continue using the shared `httpx`-based `HttpClient`.

### Validation

Confirmed via a live side-by-side experiment (`diagnose_curl_cffi.py`,
standalone test harness, not part of the production pipeline):

| Engine     | httpx                   | curl_cffi                                |
| ---------- | ----------------------- | ---------------------------------------- |
| Mojeek     | HTTP 200, 10/10 results | HTTP 200, 10/10 results (no change)      |
| Yahoo      | HTTP 500, 0 results     | HTTP 200, 9 compTitle / 30 `/RU=`links |
| Bing       | HTTP 200, working       | HTTP 200, working (no change)            |
| DuckDuckGo | HTTP 200, working       | HTTP 200, working (no change)            |

Only Yahoo benefited from the transport change; Mojeek/Bing/DDG were left
untouched on `httpx`.

### Dependencies

* Added `curl_cffi>=0.7.0` to `requirements.txt` (Yahoo-only).

## v1.1.2 — 2026-06-19

### Bug Fixes

* **Mojeek engine** – removed `&fmt=html` from search URL to avoid bot detection (403 Forbidden).
* **HTTP client** – updated base headers to modern Chrome 136 fingerprint (Cache-Control, full Accept, Sec-CH-UA).
* **Main scraper** – Mojeek warmup now uses the shared `HttpClient` instance to preserve session cookies.
* **Diagnose** – fixed unused import (`xmlrpc.client`) and unused variable (`warm1`) to satisfy ruff linting.

## v1.1.1 — 2026-05-12

### Test updates

* `tests/test_email_utils.py`: Added 6 tests covering previously untested
  core functions — `decode_cloudflare_email`, `score_email`, and
  `best_email`. Test suite now has 78 tests total.

| Test                                                 | Function                      | What it verifies                                                                                                             |
| ---------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `test_decode_cloudflare_known_fixture`             | `decode_cloudflare_email()` | Decodes a pre-computed XOR fixture (`key=0x1a`, plaintext `hello@example.com`) without any network or browser dependency |
| `test_decode_cloudflare_invalid_hex_returns_empty` | `decode_cloudflare_email()` | Returns `""`for malformed hex input and empty string input                                                                 |
| `test_score_email_tier_1_personal`                 | `score_email()`             | Personal-name local part scores 1 (highest quality)                                                                          |
| `test_score_email_tiers_2_3_and_999`               | `score_email()`             | Priority generic → 2; other generic → 3; skip keyword and junk domain → 999                                               |
| `test_best_email_returns_lowest_score`             | `best_email()`              | Selects the lowest-scoring candidate from a mixed-tier list                                                                  |
| `test_best_email_discards_junk_score_999`          | `best_email()`              | Returns `""`when all candidates score 999; returns valid candidate from mixed junk+valid list                              |

---

## v1.1.0 — 2026-05-02

### Bug Fixes

| Ref   | File                                         | What changed                                                                                                                                                                                                                                                                                                                          |
| ----- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BUG-1 | `core/controls.py`,`main.py`             | Added `interruptible_sleep()`to `controls.py`. Phase 1 inter-engine and inter-query delays now use it instead of bare `time.sleep()`.`ControlListener`is now instantiated in `main.py`at startup so P/Q/R/S/W keys work instantly during any sleep.                                                                         |
| BUG-2 | `pipeline/data_cleaner.py`                 | Company name is now derived from the domain (`derive_name_from_domain()`) instead of the search-engine page title. Uses 2-pass CamelCase splitting (before lowercasing) + hyphen/underscore splitting. Example:`alpha-block-management.co.uk`→`Alpha Block Management`.                                                        |
| BUG-3 | `core/email_utils.py`                      | Added `_PLACEHOLDER_DOMAINS`and `_PLACEHOLDER_LOCALS`blocklists. Addresses like `user@domain.com`,`john@doe.com`, and `filler@godaddy.com`are now rejected before they reach scoring.                                                                                                                                       |
| BUG-4 | `core/email_utils.py`                      | Mailto query strings (`?subject=…`) and URL fragments (`#…`) are now stripped from every extracted email address before validation.                                                                                                                                                                                             |
| BUG-5 | `core/email_utils.py`                      | HTML entities in phone strings are decoded with `html.unescape()`before extraction. Phone candidates containing a decimal point (`412 132.305`) or three+ consecutive zeros are rejected as prices/placeholder numbers.                                                                                                           |
| BUG-6 | `pipeline/data_cleaner.py`,`enricher.py` | Directory domains are now hard-excluded in `DataCleaner.process()`— no `CleanRecord`is created.`enricher.py`additionally filters any row where `flagged=YES`and `flag_reason=directory`from its input.`threebestrated.co.uk`,`trovit.co.uk`,`idobusiness.co.uk`,`servicevista.co.uk`moved to `_ALWAYS_EXCLUDED`. |
| BUG-7 | `pipeline/data_cleaner.py`                 | `_normalise_to_root()`threshold changed from `>= 2`segments to `>= 1`. Any URL with a path (`/property-management-london`) is collapsed to root (`/`). Cuts ~30% of Phase 2 HTTP requests.                                                                                                                                  |

### Improvements

| Ref       | File                                       | What changed                                                                                                                                                                                                                                                                                                      |
| --------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| IMP-1     | `enricher.py`                            | Phase 2 Pass 1 (HTTP) now runs concurrently via `ThreadPoolExecutor`. Worker count controlled by `enricher_workers`in `config.yaml`(default 5). Thread-safe writes via `threading.Lock`. Playwright Pass 2 remains sequential.                                                                            |
| IMP-2     | `pipeline/data_cleaner.py`,`config.py` | `GEO_SUSPECT_TLDS`list added to `config.py`(default empty). Domains whose TLD matches get `flagged=True, flag_reason='geo-suspect'`and a `-2`score penalty.                                                                                                                                               |
| IMP-3     | Multiple files                             | All UK-specific hardcoding removed: city lists (`_UK_CITIES`,`_US_CITIES`),`.co.uk`scoring bonus,`.gov.uk`/`.org.uk`auto-flag,`en-GB`Accept-Language header, industry-specific `generic_email_keywords`.`SCORE_BOOST_KEYWORDS`added to `config.py`(default empty). Tool is now general-purpose. |
| IMP-4     | `enricher.py`                            | Email list deduplicated with `list(set(emails))`before `best_email()`selection.`junk_email_domains`expanded to match `_PLACEHOLDER_DOMAINS`in `email_utils.py`.                                                                                                                                         |
| IMP-5     | `main.py`                                | Per-engine stats table printed in Phase 1 completion summary (engine, leads found, pages completed).                                                                                                                                                                                                              |
| IMP-6     | `engines/bing.py`                        | Bing loop detection added. If page 2 returns a domain set that is a subset of page 1's domains, engine logs `"Results are looping (geo-block confirmed)"`and sets `is_banned = True`immediately rather than running all 20 pages.                                                                             |
| CF-FIX    | `core/email_utils.py`                    | Fixed Cloudflare regex typo: closing quote was inside the capture group (`([a-f0-9]+"`), causing zero matches. Correct pattern:`([a-f0-9]+)"`.                                                                                                                                                                |
| CAMEL-FIX | `pipeline/data_cleaner.py`               | `derive_name_from_domain()`now does CamelCase detection**before**lowercasing the domain string. Fixes `JPropertyManagement.com`→`J Property Management`(was `Jpropertymanagement`).                                                                                                                |

### Test updates

* `tests/test_cleaner.py`: Updated `test_derive_name_from_domain` expectations; added `test_directory_domain_produces_none`, `test_normalise_to_root_single_segment`, `test_geo_suspect_flag`, `test_irrelevance_flag`.
* `tests/test_email_utils.py`: Added `test_mailto_query_string_stripped`, `test_placeholder_domain_rejected`, `test_placeholder_local_rejected`, `test_html_entity_phone_decoded`, `test_decimal_phone_rejected`, `test_zero_loop_phone_rejected`.

---

## v1.0.0 — 2026-04-01

Initial release.
