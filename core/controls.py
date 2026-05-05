"""
core.controls — Runtime controls, system health checks, and background auto-save.

Public API
----------
State                                            — shared mutable run state (paused, stop, handoff).
ControlListener(state, ctx)                      — background keyboard listener thread.
AutoSaver(found, out_file, cfg, stats, interval) — background periodic save thread.
interruptible_sleep(state, seconds)              — sleep that exits immediately on state.stop.
check_cmd_file(state, cmd_file, ckpt_file)       — read + clear command.txt.
wait_if_paused(state, ctx, cmd_file, ckpt_file)  — block until unpaused or stopped.
should_stop(state, stop_at)                      — check quit-flag + wall-clock time.
has_internet()                                   — quick TCP connectivity probe.
wait_for_internet(state)                         — auto-pause until internet returns.
check_disk(min_mb)                               — warn when free disk is low.
"""

from __future__ import annotations

import os
import platform
import select
import shutil
import socket
import sys
import threading
import time
from datetime import datetime

from core._log import log
from core.storage import save_output

# ── Shared run state ──────────────────────────────────────────────────────────

class State:
    """
    Shared mutable run state accessed from both the main thread and
    ControlListener.

    Attributes
    ----------
    paused  : When True the main loop idles in wait_if_paused().
    stop    : When True the main loop exits at the next checkpoint.
    handoff : When True Phase 1 ended via W key; Phase 2 will be offered.
    """
    paused:  bool = False
    stop:    bool = False
    handoff: bool = False


# ── Audio alerts ──────────────────────────────────────────────────────────────

def _beep(kind: str = "error") -> None:
    """
    Emit an audio alert.

    Windows  — winsound frequency sequences (non-blocking).
    All else — console bell character.
    """
    try:
        if platform.system() == "Windows":
            import winsound
            B = winsound.Beep
            sequences: dict = {
                "start":  [(500, 100), (700, 100), (900, 200)],
                "resume": [(600, 150), (900, 250)],
                "done":   [(600, 100), (800, 100), (1000, 100), (1200, 300)],
                "stop":   [(900, 200), (600, 400)],
            }
            for freq, dur in sequences.get(kind, [(350, 120)]):
                B(freq, dur)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


# ── Keyboard listener ─────────────────────────────────────────────────────────

class ControlListener:
    """
    Listen for interactive keyboard commands in a background daemon thread.

    Platform behaviour
    ------------------
    Windows     — msvcrt.kbhit() / getch() single-key detection (no Enter required).
    Mac / Linux — select-based stdin line reading (type letter + Enter).

    Supported commands
    ------------------
    P   toggle pause / resume
    R   resume (if paused)
    Q   quit and save
    S   print current status
    W   end Phase 1 early and queue Phase 2 (handoff)
    """

    def __init__(self, state: State, ctx: dict) -> None:
        self._state = state
        self._ctx   = ctx
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()

    def _handle(self, key: str) -> None:
        key = key.strip().upper()
        if not key:
            return
        key = key[0]
        s   = self._state

        if key == "P":
            s.paused = not s.paused
            if s.paused:
                log("PAUSED — press P or R to resume", "warn")
                _beep("stop")
            else:
                log("RESUMED", "good")
                _beep("resume")
        elif key == "R" and s.paused:
            s.paused = False
            log("RESUMED", "good")
            _beep("resume")
        elif key == "Q":
            s.stop = True
            log("QUIT — saving and exiting …", "warn")
            _beep("stop")
        elif key == "S":
            log(
                f"status → found:{self._ctx.get('found', 0)} "
                f"| done:{self._ctx.get('done', 0)}"
            )
        elif key == "W":
            # W key triggers Phase 1 → Phase 2 handoff.
            # Sets both handoff and stop so the Phase 1 loop exits cleanly,
            # then main.py detects handoff=True and offers the Phase 2 prompt.
            s.handoff = True
            s.stop    = True
            log("HANDOFF — Phase 1 stopping, Phase 2 will be offered...", "warn")
            _beep("stop")

    def _listen(self) -> None:
        if platform.system() == "Windows":
            import msvcrt
            while True:
                if msvcrt.kbhit():
                    try:
                        key = msvcrt.getch().decode(errors="ignore")
                        while msvcrt.kbhit():
                            msvcrt.getch()
                        self._handle(key)
                    except Exception:
                        pass
                time.sleep(0.05)
        else:
            while True:
                try:
                    ready, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if ready:
                        line = sys.stdin.readline()
                        if line:
                            self._handle(line.strip())
                except Exception:
                    time.sleep(0.1)


# ── Background auto-saver ─────────────────────────────────────────────────────

class AutoSaver:
    """
    Background daemon thread that persists results every interval seconds.

    Parameters
    ----------
    found    : The live found dict (shared reference — reads current state).
    out_file : Destination output path.
    cfg      : Config dict (passed through to save_output).
    stats    : Run statistics dict (passed through to save_output).
    interval : Save every this many seconds (minimum 1).
    """

    def __init__(
        self,
        found:    dict,
        out_file: str,
        cfg:      dict,
        stats:    dict,
        interval: int = 60,
    ) -> None:
        self._found    = found
        self._out_file = out_file
        self._cfg      = cfg
        self._stats    = stats
        self._interval = max(1, interval)
        self._stopped  = False
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        ticks = 0
        while not self._stopped:
            time.sleep(1)
            ticks += 1
            if ticks >= self._interval and not self._stopped:
                ticks = 0
                try:
                    save_output(self._found, self._out_file, self._cfg, self._stats)
                except Exception:
                    pass

    def stop(self) -> None:
        """Signal the thread to stop (daemon — won't block process exit)."""
        self._stopped = True


# ── Interruptible sleep ───────────────────────────────────────────────────────

def interruptible_sleep(state: State, seconds: float) -> None:
    """
    Sleep for up to `seconds` total time, but exit early if state.stop is set.

    Polls in 0.1-second increments so pressing Q during a long inter-engine
    delay (e.g. 89 seconds) exits within 0.1 seconds rather than waiting for
    the full sleep to complete.

    Also honours state.paused — spins in place until resumed, then continues
    the remaining sleep time.

    Parameters
    ----------
    state   : Shared run state. Checked every 0.1 seconds.
    seconds : Maximum sleep duration in seconds.

    Why this exists
    ---------------
    The original bare time.sleep() between engine switches made the P/Q/R/S
    controls completely unresponsive during the full inter-engine delay.
    This function polls state.stop every 0.25 s so controls remain live.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if state.stop:
            break
        if state.paused:
            # Spin while paused; this does not consume the remaining deadline
            while state.paused and not state.stop:
                time.sleep(0.1)
        time.sleep(0.1)


# ── Command file ──────────────────────────────────────────────────────────────

def check_cmd_file(state: State, cmd_file: str, checkpoint_file: str) -> None:
    """
    Read a single command from command.txt and clear the file.

    Valid commands (case-insensitive)
    ---------------------------------
    pause   — set state.paused = True
    resume  — set state.paused = False
    r       — alias for resume
    stop    — set state.stop = True
    q       — alias for stop
    fresh   — delete the checkpoint file (restart on next run)

    Parameters
    ----------
    state           : Shared run state to mutate.
    cmd_file        : Path to command.txt.
    checkpoint_file : Path to the checkpoint JSON (used by 'fresh' command).
    """
    if not os.path.exists(cmd_file):
        return
    try:
        with open(cmd_file, encoding="utf-8") as _f:
            cmd = _f.read().strip().lower()
        if not cmd:
            return
        with open(cmd_file, "w") as _f:
            _f.write("")

        if cmd == "pause":
            state.paused = True
            log("PAUSED (cmd file)", "warn")
            _beep("stop")
        elif cmd in ("resume", "r"):
            state.paused = False
            log("RESUMED (cmd file)", "good")
            _beep("resume")
        elif cmd in ("stop", "q"):
            state.stop = True
            log("STOP — saving …", "warn")
            _beep("stop")
        elif cmd == "fresh":
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
            log("Checkpoint cleared — restart the script to begin fresh", "warn")
    except Exception:
        pass


# ── Pause helper ──────────────────────────────────────────────────────────────

def wait_if_paused(
    state:           State,
    ctx:             dict,
    cmd_file:        str,
    checkpoint_file: str,
) -> None:
    """
    Block the calling thread until state.paused is cleared or a stop is requested.

    Polls every 300 ms and re-checks command.txt on each tick.

    Parameters
    ----------
    state           : Shared run state.
    ctx             : Live context dict (not currently used here; kept for API
                      compatibility with call sites that pass it).
    cmd_file        : Path to command.txt checked on each poll tick.
    checkpoint_file : Passed through to check_cmd_file for the 'fresh' command.
    """
    while state.paused and not state.stop:
        check_cmd_file(state, cmd_file, checkpoint_file)
        time.sleep(0.3)


# ── Stop-condition check ──────────────────────────────────────────────────────

def should_stop(state: State, stop_at: str) -> bool:
    """
    Return True if a quit was requested or the wall-clock stop time has passed.

    Parameters
    ----------
    state   : Shared run state.
    stop_at : 24-hour "HH:MM" string, or "" to disable time-based stopping.
    """
    if state.stop:
        return True
    if not stop_at:
        return False
    try:
        return datetime.now().strftime("%H:%M") >= stop_at
    except Exception:
        return False


# ── Internet connectivity check ───────────────────────────────────────────────

def has_internet() -> bool:
    """Test internet connectivity by attempting a TCP connection to Google DNS."""
    try:
        socket.setdefaulttimeout(3)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except Exception:
        return False


def wait_for_internet(state: State) -> None:
    """
    Auto-pause and poll every 30 seconds until internet connectivity is restored.
    Returns immediately if the connection is already up.
    """
    if has_internet():
        return
    log("Internet unreachable — auto-pausing, retrying every 30 s", "warn")
    _beep("stop")
    state.paused = True
    attempt = 0
    while not has_internet() and not state.stop:
        attempt += 1
        if attempt % 2 == 0:
            log(f"Still waiting for internet … ({attempt * 30}s elapsed)", "warn")
        time.sleep(30)
    if has_internet():
        state.paused = False
        log("Internet restored — resuming", "good")
        _beep("resume")


# ── Disk space check ──────────────────────────────────────────────────────────

def check_disk(min_mb: int = 500) -> bool:
    """
    Warn and return False if free disk space falls below min_mb megabytes.
    Called periodically during long runs to prevent silent output corruption.
    """
    free_mb = shutil.disk_usage(".").free // (1024 * 1024)
    if free_mb < min_mb:
        log(
            f"Low disk space: {free_mb} MB free (minimum {min_mb} MB) — pausing",
            "warn",
        )
        _beep("stop")
        return False
    return True
