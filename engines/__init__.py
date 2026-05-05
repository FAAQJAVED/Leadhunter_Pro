from engines.bing import BingEngine
from engines.duckduckgo import DuckDuckGoEngine
from engines.mojeek import MojeekEngine
from engines.yahoo import YahooEngine

# Engine status summary:
#
# Mojeek      PRIMARY     a.ob selector, UK index, zero bot detection. Always runs first.
#
# DuckDuckGo  WORKING     DDG Lite POST endpoint (lite.duckduckgo.com).
#                         Per-engine warmup runs immediately before the first POST (≤2s gap).
#                         Prevents HTTP 202 bot challenges.
#
# Yahoo       WORKING     Dual-pattern CSS selector covers both anchor layouts:
#                           Pattern A: div.compTitle > a[href*=/RU=]
#                           Pattern B: div.compTitle > h3 > a[href*=/RU=]
#                         Per-engine warmup harvests session cookies.
#
# Bing        GEO-LOCK    Set BING_PROXY in config.py for reliable results.
#                         Auto-skips after page 1 if all results fail English check.

ENGINE_MAP = {
    'mojeek':     MojeekEngine,
    'yahoo':      YahooEngine,
    'duckduckgo': DuckDuckGoEngine,
    'ddg':        DuckDuckGoEngine,
    'duck':       DuckDuckGoEngine,
    'bing':       BingEngine,
}
