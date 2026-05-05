"""
core._log — Shared logging helpers used across all core modules.

Keeping this in a single place prevents circular imports and ensures
every module routes its output through tqdm.write() when a progress
bar is active (avoiding garbled terminal output).

Public API
----------
log(msg, kind)    — print an icon-prefixed, elapsed-time-stamped line.
elapsed()         — return "[Xm YYs]" since the process started.
set_start_time(t) — called once by enricher.main() at startup.
set_active_bar(bar) — called by pass runners when a tqdm bar is live.
"""

from __future__ import annotations

import time
from typing import Optional

_start_time: float = time.time()
_active_bar: Optional[object] = None


def set_start_time(t: float) -> None:
    """Record the script-start wall time for elapsed() calculations."""
    global _start_time
    _start_time = t


def set_active_bar(bar: Optional[object]) -> None:
    """
    Register (or clear) the active tqdm progress bar.

    While a bar is registered, log() routes through tqdm.write() so that
    log lines are inserted above the bar rather than overwriting it.
    """
    global _active_bar
    _active_bar = bar


def elapsed() -> str:
    """Return elapsed wall time since set_start_time() as '[Xm YYs]'."""
    s = int(time.time() - _start_time)
    return f"[{s // 60}m{s % 60:02d}s]"


_ICONS: dict[str, str] = {
    "good":  "✅",
    "warn":  "⚠ ",
    "error": "❌",
    "info":  "  ",
    "dim":   "  ",
}


def log(msg: str, kind: str = "info") -> None:
    """
    Print a timestamped, icon-prefixed status line.

    Routes through tqdm.write() when a progress bar is active so the
    bar stays rendered below the log output rather than being clobbered.

    Parameters
    ----------
    msg:  The message text.
    kind: One of "good" | "warn" | "error" | "info" | "dim".
    """
    text = f"{elapsed():>9} {_ICONS.get(kind, '  ')} {msg}"
    if _active_bar is not None:
        _active_bar.write(text)          # type: ignore[attr-defined]
    else:
        print(text, flush=True)
