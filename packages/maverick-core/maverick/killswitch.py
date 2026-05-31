"""Global killswitch for running agents.

Two ways to halt:
  1. **File trigger**: ``touch ~/.maverick/HALT``  (default path; override
     via ``MAVERICK_HALT_FILE``). Polled cheaply at tool-call boundaries.
  2. **In-process trigger**: any thread calls ``halt(reason)`` and every
     ``check()`` call afterward raises ``Halted``.

Agent kernels call ``check()`` at tool-call boundaries and at each
turn. If a halt is active, ``Halted`` is raised, the goal is recorded
as halted in the audit log, and the orchestrator stops cleanly.

The file trigger lets a user (or operator) abort a swarm from outside
the process — handy when you realize the agent is about to do
something expensive or wrong.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _default_halt_file() -> Path:
    """Default HALT path, resolved fresh each call.

    Must NOT be cached at import time: a process that re-homes after import
    (a daemon, an embedder, or the test home-isolation fixture) would
    otherwise keep watching the *old* home's HALT file. Honoring the current
    ``Path.home()`` per call keeps the killswitch trustworthy — the one
    place we can least afford a stale path.
    """
    return Path.home() / ".maverick" / "HALT"


class Halted(Exception):
    """Raised by ``check()`` when a halt is active."""

    def __init__(self, reason: str, source: str):
        super().__init__(f"halted: {reason} (source={source})")
        self.reason = reason
        self.source = source


_state_lock = threading.Lock()
_in_process_halt: tuple[str, str] | None = None  # (reason, source)
_last_file_check_ts: float = 0.0
_last_file_present: bool = False


def _halt_file_path() -> Path:
    override = os.environ.get("MAVERICK_HALT_FILE")
    return Path(override) if override else _default_halt_file()


def halt(reason: str, source: str = "manual") -> None:
    """Trigger an in-process halt. All subsequent check() calls raise."""
    global _in_process_halt
    with _state_lock:
        _in_process_halt = (reason, source)
    log.warning("killswitch: halt set (%s, source=%s)", reason, source)
    try:
        from .audit import EventKind, record
        record(EventKind.HALT, source=source, detail=reason)
    except Exception:  # pragma: no cover -- never crash on audit
        pass


def clear() -> None:
    """Reset the in-process halt. Doesn't delete the HALT file."""
    global _in_process_halt
    with _state_lock:
        _in_process_halt = None


def _file_halt_active(min_interval: float = 1.0) -> bool:
    """Check the HALT file at most once per ``min_interval`` seconds.

    Avoids stat-ing the filesystem on every tool call. The 1s cache is
    invisible to humans triggering halts but cheap enough to not matter.
    """
    global _last_file_check_ts, _last_file_present
    now = time.time()
    if now - _last_file_check_ts < min_interval:
        return _last_file_present
    _last_file_check_ts = now
    try:
        _last_file_present = _halt_file_path().exists()
    except OSError:
        _last_file_present = False
    return _last_file_present


def check() -> None:
    """Raise ``Halted`` if any halt source is active."""
    with _state_lock:
        ip = _in_process_halt
    if ip is not None:
        raise Halted(ip[0], ip[1])
    if _file_halt_active():
        raise Halted(f"HALT file present at {_halt_file_path()}", "file")


def is_active() -> bool:
    """Non-raising query. Useful for UI."""
    try:
        check()
    except Halted:
        return True
    return False
