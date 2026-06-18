"""
LeadHunter Pro — Engine Diagnostic

Tests each search engine, prints selector matches and sample URLs.
Run this before main.py to verify engines are healthy.

Usage
-----
  python diagnose.py                    # test mojeek, duckduckgo, yahoo (default)
  python diagnose.py --bing             # test only Bing (run with VPN/proxy)
  python diagnose.py --all              # test all 4 engines
  python diagnose.py --mojeek          # test only Mojeek
  python diagnose.py --ddg             # test only DuckDuckGo
  python diagnose.py --yahoo           # test only Yahoo
  python diagnose.py --no-wait         # skip inter-engine sleeps (dev mode)
  python diagnose.py -q "letting agents Manchester"
"""

from __future__ import annotations

import argparse
import os
import random
import time
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_DEFAULT_ENGINES = ["mojeek", "duckduckgo", "yahoo"]
_ALL_ENGINES     = ["mojeek", "duckduckgo", "yahoo", "bing"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="LeadHunter Pro — Engine Diagnostic: tests engines and prints selector matches."
    )
    p.add_argument("--mojeek", action="store_true", help="Test only Mojeek")
    p.add_argument("--ddg",    action="store_true", help="Test only DuckDuckGo")
    p.add_argument("--yahoo",  action="store_true", help="Test only Yahoo")
    p.add_argument("--bing",   action="store_true",
                   help="Test Bing (run with VPN/proxy active for valid results)")
    p.add_argument("--all",    action="store_true", help="Test all 4 engines")
    p.add_argument("--engine", "-e", choices=_ALL_ENGINES, default=None, metavar="ENGINE",
                   help=f"Test only one engine. Choices: {', '.join(_ALL_ENGINES)}")
    p.add_argument("--query", "-q", default="block management companies London",
                   help='Search query to use (default: "block management companies London")')
    p.add_argument("--no-wait", action="store_true",
                   help="Skip inter-engine sleeps (fast dev/testing mode)")
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

    if args.all:
        args.selected_engines = list(_ALL_ENGINES)
    elif shorthand:
        args.selected_engines = shorthand
    elif args.engine:
        args.selected_engines = [args.engine]
    else:
        args.selected_engines = list(_DEFAULT_ENGINES)

    return args


def _qs(q: str) -> str:
    return q.replace(" ", "+")


# ---------------------------------------------------------------------------
# Bing geo check
# ---------------------------------------------------------------------------
_LOCALE_PATTERNS = (
    "/de/", "/de-de/", "/ja/", "/ja-jp/", "/sr/", "/sr-latn/",
    "/fr/", "/fr-fr/", "/es/", "/es-es/", "/it/", "/it-it/",
    "/nl/", "/pl/", "/pt/", "/ru/", "/tr/", "/ko/", "/zh/",
    "hl=de", "hl=ja", "lang=de", "locale=de", "language=de",
)


def _is_english_result(title: str, description: str = "") -> bool:
    def _pct_non_ascii(text: str) -> float:
        if not text:
            return 0.0
        return sum(1 for c in text if ord(c) > 127) / len(text)
    if _pct_non_ascii(title) >= 0.30:
        return False
    if description and len(description) > 50:
        if _pct_non_ascii(description) >= 0.25:
            return False
        if any(p in description.lower() for p in _LOCALE_PATTERNS):
            return False
    return True


# ---------------------------------------------------------------------------
# Yahoo URL extractor
# ---------------------------------------------------------------------------
def _extract_yahoo_url(href: str) -> str:
    if not href:
        return ""
    if "/RU=" in href:
        try:
            ru   = href.split("/RU=")[1].split("/")[0]
            real = unquote(ru)
            if real.startswith("http") and "yahoo.com" not in real:
                return real
        except Exception:
            pass
    if href.startswith("http") and "yahoo.com" not in href:
        return href
    return ""


def _base_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host.split(":")[0]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Headers & UA rotation – modern Chrome 136 set
# ---------------------------------------------------------------------------
# Base headers for warmup and search – these mimic a real Chrome browser
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Sec-CH-UA": '"Chromium";v="136", "Google Chrome";v="136", "Not:A-Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

# Engine-specific overrides
YAHOO_HEADERS = {**BASE_HEADERS, "Referer": "https://search.yahoo.com/"}
DDG_HEADERS = {**BASE_HEADERS, "Referer": "https://duckduckgo.com/", "Origin": "https://duckduckgo.com"}
BING_HEADERS = {**BASE_HEADERS,
    "X-MSEdge-ClientIP": "81.141.0.1",
    "X-MSEdge-Market":   "en-GB",
    "X-Search-Location": "lat:51.5074;long:-0.1278;re:1000",
}
MOJEEK_HEADERS = {**BASE_HEADERS,
    "Referer": "https://www.mojeek.com/",
    "Sec-Fetch-Site": "same-origin",   # navigation from homepage to search
}

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]
_last_ua = [BASE_HEADERS["User-Agent"]]


def _rotate_ua(headers: dict) -> dict:
    """Pick a UA different from the last one and update headers."""
    pool = [ua for ua in _UA_POOL if ua != _last_ua[0]]
    if not pool:
        pool = _UA_POOL
    ua = random.choice(pool)
    _last_ua[0] = ua
    # Update Sec-CH-UA to match the new Chrome version
    m = __import__('re').search(r'Chrome/(\d+)', ua)
    sec_ch_ua = f'"Chromium";v="{m.group(1)}", "Google Chrome";v="{m.group(1)}", "Not:A-Brand";v="99"' if m else headers.get("Sec-CH-UA", "")
    return {**headers, "User-Agent": ua, "Sec-CH-UA": sec_ch_ua}


def build_engines(query: str) -> dict:
    """Return engine configs; Mojeek URL no longer uses &fmt=html."""
    return {
        "mojeek": {
            "name": "mojeek", "label": "Mojeek — primary engine",
            "url": (f"https://www.mojeek.com/search?q={_qs(query)}"
                    f"&lang=en&hp=0&arc=none"),   # &fmt=html removed
            "method": "GET", "data": None,
            "headers": MOJEEK_HEADERS,
            "warmup_needed": True,
        },
        "duckduckgo": {
            "name": "duckduckgo", "label": "DDG Lite POST (lite.duckduckgo.com/lite/)",
            "url": "https://lite.duckduckgo.com/lite/",
            "method": "POST",
            "data": {"q": query, "s": "0", "kl": "wt-wt", "kp": "-1"},
            "headers": DDG_HEADERS,
            "warmup_needed": True,
        },
        "yahoo": {
            "name": "yahoo", "label": "Yahoo Search HTML (own index, no geo-lock)",
            "url": (f"https://search.yahoo.com/search"
                    f"?p={_qs(query)}&b=1&pz=10&vl=lang_en&fl=1"),
            "method": "GET", "data": None,
            "headers": YAHOO_HEADERS,
            "warmup_needed": True,
        },
        "bing": {
            "name": "bing", "label": "Bing RSS + geo-override headers (en-GB, London coords)",
            "url": (f"https://www.bing.com/search?q={_qs(query)}"
                    f"&format=RSS&first=1&mkt=en-GB&cc=GB"
                    f"&setlang=en-GB&ensearch=1&count=10"),
            "method": "GET", "data": None,
            "headers": BING_HEADERS,
            "warmup_needed": False,
        },
    }


# ---------------------------------------------------------------------------
# Selector table
# ---------------------------------------------------------------------------
def run_selectors(soup: BeautifulSoup, name: str,
                  rss_parsed: int = 0, geo_passed: int = 0) -> dict:
    yahoo_primary = len([
        a for a in soup.select("div.compTitle > a[href], div.compTitle > h3 > a[href]")
        if "/RU=" in a.get("href", "")
    ])

    d: dict = {}
    if name == "bing":
        d["Bing: RSS parsed (ET)"] = rss_parsed
        d["Bing: RSS geo-passed"]  = geo_passed

    d.update({
        "Bing: li.b_algo":               len(soup.select("li.b_algo")),
        "Yahoo: div.compTitle":          len(soup.select("div.compTitle")),
        "Yahoo: compTitle>a /RU= (dual-pattern)": yahoo_primary,
        "Yahoo: a[href*=/RU=]":          len([
            a for a in soup.select("a[href]") if "/RU=" in (a.get("href") or "")
        ]),
        "DDG: a.result-link":            len(soup.select("a.result-link")),
        "DDG: td.result-snippet":        len(soup.select("td.result-snippet")),
        "Mojeek: a.ob":                  len(soup.select("a.ob")),
        "Mojeek: h2 a[href]":            len(soup.select("h2 a[href]")),
        "Any <h2>":                      len(soup.select("h2")),
        "Any <a href=http>":             len([
            a for a in soup.select("a[href]")
            if (a.get("href") or "").startswith("http")
        ]),
    })
    return d


def count_results(soup: BeautifulSoup, name: str, geo_passed: int = 0) -> int:
    if name == "bing":
        return geo_passed

    if name == "yahoo":
        seen_d: set = set()
        n = 0
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "/RU=" not in href:
                continue
            u = _extract_yahoo_url(href)
            if not u:
                continue
            d = _base_domain(u)
            if d and d not in seen_d:
                seen_d.add(d)
                n += 1
        return n

    if name == "mojeek":
        return len(soup.select("a.ob"))

    if name == "duckduckgo":
        return len(soup.select("a.result-link"))

    return 0


def sample_urls(soup: BeautifulSoup, name: str, html: str,
                geo_passed: int = 0, n: int = 5) -> tuple:
    """Returns (urls, geo_rejected)."""
    seen, urls = set(), []

    if name == "bing":
        if geo_passed == 0:
            return [], True
        try:
            root = ET.fromstring(html.lstrip("\ufeff").strip())
            for item in root.findall(".//item")[:n]:
                lnk  = item.find("link")
                ttl  = item.find("title")
                desc = item.find("description")
                t    = (ttl.text  or "") if ttl  is not None else ""
                d    = (desc.text or "") if desc is not None else ""
                if lnk is not None and lnk.text and _is_english_result(t, d):
                    urls.append(lnk.text.strip())
        except Exception:
            pass
        return urls, False

    if name == "yahoo":
        seen_domains: set = set()
        for a in soup.select("a[href]"):
            if "/RU=" not in (a.get("href") or ""):
                continue
            u = _extract_yahoo_url(a.get("href", ""))
            if not u or u in seen:
                continue
            domain = _base_domain(u)
            if domain in seen_domains:
                continue
            seen.add(u)
            seen_domains.add(domain)
            urls.append(u)
            if len(urls) >= n:
                break
        return urls, False

    if name == "duckduckgo":
        for a in soup.select("a.result-link[href]"):
            h = a.get("href", "")
            if h.startswith("http") and h not in seen:
                seen.add(h)
                urls.append(h)
            if len(urls) >= n:
                break
        return urls, False

    # Mojeek
    for a in soup.select("a.ob[href]"):
        h = a.get("href", "")
        if h.startswith("http") and h not in seen:
            seen.add(h)
            urls.append(h)
        if len(urls) >= n:
            break
    if not urls:
        for a in soup.select("h2 a[href]"):
            h = a.get("href", "")
            if h.startswith("http") and h not in seen:
                seen.add(h)
                urls.append(h)
            if len(urls) >= n:
                break
    return urls, False


def estimate_overlap(engine_urls: dict) -> list:
    seen_domains: set = set()
    rows = []
    for name in _ALL_ENGINES:
        urls = engine_urls.get(name, [])
        if not urls and name not in engine_urls:
            continue
        domains = [_base_domain(u) for u in urls if _base_domain(u)]
        new = sum(1 for d in domains if d not in seen_domains)
        seen_domains.update(domains)
        rows.append((name, len(urls), new))
    return rows


def main() -> None:
    args = _parse_args()

    try:
        import brotli  # noqa: F401
        brotli_ok = True
    except ImportError:
        brotli_ok = False

    # Load proxy from environment (reuse BING_PROXY for all engines if you like)
    bing_proxy = ""
    try:
        from config import BING_PROXY
        bing_proxy = BING_PROXY
    except ImportError:
        pass
    # Optionally, set a separate proxy for Mojeek:
    mojeek_proxy = os.getenv("MOJEEK_PROXY", bing_proxy)   # fallback to BING_PROXY

    all_engine_defs = build_engines(args.query)
    engines = [all_engine_defs[name] for name in args.selected_engines
               if name in all_engine_defs]

    os.makedirs("debug_html", exist_ok=True)

    print("=" * 70)
    print("  LEADHUNTER PRO — ENGINE DIAGNOSTIC")
    print(f'  Query: "{args.query}"')
    print(f"  Mode : {', '.join(e['name'] for e in engines)}")
    if args.no_wait:
        print("  Speed: --no-wait active (minimal sleeps)")
    print("=" * 70)

    print("\n[Pre-flight]")
    print(f"  brotli : {'OK installed' if brotli_ok else 'MISSING — pip install brotli'}")
    if len(engines) > 1:
        print("  Warmups: per-engine, run immediately before each request")

    summary:     dict = {}
    engine_urls: dict = {}

    for idx, eng in enumerate(engines):
        name = eng["name"]
        print(f"\n{'─' * 70}")
        print(f"  ENGINE : {name.upper()}  |  {eng['label']}")

        if name == "bing":
            if bing_proxy:
                print(f"  Proxy  : {bing_proxy[:50]}{'...' if len(bing_proxy) > 50 else ''}")
            else:
                print("  Proxy  : none (set BING_PROXY in config.py for UK results)")
            print("  Note   : Run with VPN/proxy active for valid UK results")
        elif name == "mojeek" and mojeek_proxy:
            print(f"  Proxy  : {mojeek_proxy[:50]}{'...' if len(mojeek_proxy) > 50 else ''}")

        print(f"{'─' * 70}")

        # Prepare client for this engine
        headers = _rotate_ua(eng["headers"])
        proxy_url = mojeek_proxy if name == "mojeek" else (bing_proxy if name == "bing" else None)

        client_kwargs = {
            "headers": headers,
            "timeout": httpx.Timeout(15.0, connect=10.0, read=30.0),
            "follow_redirects": True,
            "http2": True,   # if httpx[http2] installed; otherwise ignored
        }
        if proxy_url:
            client_kwargs["proxies"] = {"http://": proxy_url, "https://": proxy_url}

        # Create a single client for warmup + search
        try:
            client = httpx.Client(**client_kwargs)
        except Exception as e:
            print(f"  ERROR creating client: {e}")
            summary[name] = 0
            continue

        # ---- Warmup ----
        if eng.get("warmup_needed", False):
            if name == "mojeek":
                print("  Mojeek warmup...", end=" ", flush=True)
                try:
                    warm_resp = client.get("https://www.mojeek.com/")
                    print(f"HTTP {warm_resp.status_code} ({len(dict(warm_resp.cookies))} cookies)")
                except Exception as e:
                    print(f"FAILED ({e}) — proceeding without warmup")
                # Realistic delay after warmup
                delay = 0.3 if args.no_wait else random.uniform(1.5, 3.0)
                time.sleep(delay)

            elif name == "duckduckgo":
                print("  DDG warmup...", end=" ", flush=True)
                try:
                    warm_resp = client.get("https://duckduckgo.com/")
                    print(f"HTTP {warm_resp.status_code} ({len(dict(warm_resp.cookies))} cookies)")
                except Exception as e:
                    print(f"FAILED ({e}) — proceeding without warmup")
                time.sleep(0.3 if args.no_wait else 1.5)
            elif name == "yahoo":
                print("  Yahoo warmup...", end=" ", flush=True)
                try:
                    # Step 1: yahoo.com – stores cookies in the client session
                    client.get("https://yahoo.com/")
                    time.sleep(0.3 if args.no_wait else 1.5)
                    # Step 2: search.yahoo.com with cookies from step 1
                    # Update headers for the second request (Referer, Sec-Fetch-Site)
                    client.headers.update({"Referer": "https://yahoo.com/", "Sec-Fetch-Site": "same-site"})
                    warm2 = client.get("https://search.yahoo.com/")
                    print(f"HTTP {warm2.status_code} ({len(dict(warm2.cookies))} cookies)")
                    # Restore original headers for the search request
                    client.headers.update(eng["headers"])
                except Exception as e:
                    print(f"FAILED ({e}) — proceeding without warmup")
                time.sleep(0.3 if args.no_wait else 2.0)
            # ---- Search ----
        try:
            t0 = time.monotonic()
            if eng["method"] == "GET":
                resp = client.get(eng["url"])
            else:
                resp = client.post(eng["url"], data=eng["data"])
            took = time.monotonic() - t0
            status = resp.status_code
            html = resp.text
            size = len(html)
            client.close()

            fpath = os.path.join("debug_html", f"{name}_raw.html")
            with open(fpath, "w", encoding="utf-8", errors="replace") as f:
                f.write(html)
            print(f"  HTTP {status} | {size:,} chars | {took:.1f}s | -> {fpath}")

            if status == 202:
                print("  ⚠  HTTP 202 — DDG bot challenge page; "
                      "warmup may have been blocked or IP is flagged")

            rss_parsed = 0
            geo_passed = 0
            if name == "bing":
                print("\n  [RSS PARSE]")
                try:
                    root = ET.fromstring(html.lstrip("\ufeff").strip())
                    items = root.findall(".//item")
                    rss_parsed = len(items)
                    print(f"  Items parsed by ET: {rss_parsed}")
                    for i, item in enumerate(items[:5], 1):
                        lnk = item.find("link")
                        ttl = item.find("title")
                        desc = item.find("description")
                        t = (ttl.text or "") if ttl is not None else ""
                        d = (desc.text or "") if desc is not None else ""
                        print(f"    {i}. {t[:60]}")
                        print(f"       {(lnk.text or '')[:70]}")
                        if d:
                            print(f"       desc: {d[:80]}")
                    if rss_parsed:
                        geo_passed = sum(
                            1 for it in items
                            if _is_english_result(
                                (it.find("title").text or "")
                                if it.find("title") is not None else "",
                                (it.find("description").text or "")
                                if it.find("description") is not None else "",
                            )
                        )
                        if geo_passed == rss_parsed:
                            geo_label = f"OK  {geo_passed}/{rss_parsed} results pass English check"
                        elif geo_passed > 0:
                            geo_label = f"WARN  Only {geo_passed}/{rss_parsed} pass English check"
                        else:
                            geo_label = f"FAIL  0/{rss_parsed} pass English check — all geo-rejected"
                        print(f"\n  {geo_label}")
                except ET.ParseError as e:
                    print(f"  ERROR XML parse error: {e}")

            soup = BeautifulSoup(html, "html.parser")
            sels = run_selectors(soup, name, rss_parsed=rss_parsed, geo_passed=geo_passed)

            print(f"\n  {'SELECTOR':<44} MATCHES")
            print(f"  {'─' * 44} ───────")
            for sel, n_count in sels.items():
                mark = "OK" if n_count else "X"
                print(f"  {sel:<44} {n_count:>3}  {mark}")

            urls, geo_rejected = sample_urls(soup, name, html, geo_passed=geo_passed)
            engine_urls[name] = urls

            if geo_rejected:
                print("\n  ⚠  All results geo-rejected — URLs not shown")
                print("     (need VPN/proxy for Bing — set BING_PROXY in config.py)")
            elif urls:
                print("\n  Sample URLs:")
                for u in urls:
                    print(f"    -> {u[:75]}")
            elif name != "bing":
                print("\n  WARN No sample URLs extracted — selector may have changed")

            body = html.lower()
            if "cloudflare" in body and status in (403, 503):
                print(f"\n  ERROR Cloudflare bot block (HTTP {status})")
            elif "suspended" in body or "banned" in body:
                print("\n  ERROR IP BANNED/SUSPENDED")
            if "captcha" in body:
                print("\n  WARN CAPTCHA page")
            if status == 200 and size < 5_000 and name != "bing":
                print(f"\n  WARN Only {size:,} chars — possible bot challenge")
            if html.count("\ufffd") > 50:
                print("\n  WARN Encoding issue — pip install brotli")
            if status == 500:
                print("\n  WARN HTTP 500 — rate-limit/block. "
                      "Try again in isolation: python diagnose.py --yahoo")

            result_count = count_results(soup, name, geo_passed=geo_passed)
            summary[name] = result_count

        except httpx.ConnectError as e:
            print(f"  ERROR DNS FAILED: {e}")
            print("  Retrying in 5s...")
            time.sleep(5)
            try:
                # Recreate client for retry
                client2 = httpx.Client(**client_kwargs)
                t0 = time.monotonic()
                if eng["method"] == "GET":
                    resp = client2.get(eng["url"])
                else:
                    resp = client2.post(eng["url"], data=eng["data"])
                took = time.monotonic() - t0
                status = resp.status_code
                html = resp.text
                size = len(html)
                client2.close()
                fpath = os.path.join("debug_html", f"{name}_raw.html")
                with open(fpath, "w", encoding="utf-8", errors="replace") as f:
                    f.write(html)
                print(f"  RETRY OK  HTTP {status} | {size:,} chars | {took:.1f}s")
                soup = BeautifulSoup(html, "html.parser")
                result_count = count_results(soup, name)
                summary[name] = result_count
                urls, _ = sample_urls(soup, name, html)
                engine_urls[name] = urls
                if urls:
                    print("\n  Sample URLs (retry):")
                    for u in urls:
                        print(f"    -> {u[:75]}")
            except Exception as e2:
                print(f"  RETRY also failed: {e2}")
                summary[name] = 0
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            summary[name] = 0

        if idx < len(engines) - 1:
            delay = (random.uniform(0.3, 0.8)
                     if getattr(args, "no_wait", False)
                     else random.uniform(6, 10))
            print(f"\n  [waiting {delay:.1f}s before next engine...]")
            time.sleep(delay)

    # Summary
    print(f"\n{'=' * 70}")
    print("  RESULT SUMMARY")
    print(f"  {'─' * 68}")
    _OK_THRESHOLD = {"mojeek": 10, "duckduckgo": 10, "yahoo": 7, "bing": 5}
    for eng_name, count in summary.items():
        thresh = _OK_THRESHOLD.get(eng_name, 10)
        icon = "OK" if count >= thresh else ("PARTIAL" if count > 0 else "FAIL")
        print(f"  [{icon:<7}] {eng_name:<20} {count} results")

    working = sum(1 for n, c in summary.items() if c >= _OK_THRESHOLD.get(n, 10))
    partial = sum(1 for n, c in summary.items() if 0 < c < _OK_THRESHOLD.get(n, 10))
    total = len(summary)
    print(f"\n  Engines fully working: {working}/{total}")
    if partial:
        print(f"  Engines partially working (>0 but <10 results/page): {partial}/{total}")

    if len(engine_urls) >= 2:
        present = {n: engine_urls[n] for n in _ALL_ENGINES if n in engine_urls}
        overlap_rows = estimate_overlap(present)
        if overlap_rows:
            print(f"\n  {'─' * 68}")
            print("  DOMAIN OVERLAP ESTIMATE (from sample URLs, approximate)")
            print(f"  {'─' * 68}")
            total_new = 0
            for eng_name, total_r, new_r in overlap_rows:
                note = "(first engine)" if total_new == 0 else f"~{new_r} new after overlap"
                print(f"  {eng_name:<15} {total_r} sample URLs  →  {note}")
                total_new += new_r
            est_lo = total_new * 4
            est_hi = total_new * 6
            print(f"\n  Estimated unique domains/page across active engines: ~{est_lo}–{est_hi}")
            print("  (scale × PAGES_PER_QUERY × query_count for full run estimate)")

    if "bing" not in summary:
        print("\n  Bing not tested. Run: python diagnose.py --bing (with VPN active)")
        print("  Or set BING_PROXY in config.py for automated proxy routing.")

    if working + partial >= 2:
        print("\n  -> Ready for python main.py")
    else:
        print("\n  -> Fix failing engines before running main.py")
        print("     Run: python diagnose.py --<engine>  to isolate the issue")
        print("     Then check debug_html/<engine>_raw.html for the raw response")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()