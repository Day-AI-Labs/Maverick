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

from .paths import data_dir

log = logging.getLogger(__name__)


def _default_halt_file() -> Path:
    """Default HALT path, resolved fresh each call.

    Must NOT be cached at import time: a process that re-homes after import
    (a daemon, an embedder, or the test home-isolation fixture) would
    otherwise keep watching the *old* home's HALT file. Honoring the current
    ``Path.home()`` per call keeps the killswitch trustworthy — the one
    place we can least afford a stale path.
    """
    return data_dir("HALT")


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
# Cluster-wide halt (v22): consulted from the shared world store so an emergency
# stop armed on one replica halts the whole fleet. Throttled like the file check;
# only engaged on a shared backend (Postgres).
_last_shared_check_ts: float = 0.0
_last_shared_halt: tuple[str, str] | None = None
_shared_world = None  # cached world handle for the shared-halt consult


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
    # Page the operator: a halt stops all work, so it's the canonical event an
    # SRE must hear about. No-op unless [alerts] enabled (never blocks the halt).
    try:
        from .ops_alert import alert
        alert("killswitch_tripped", f"{reason} (source={source})", severity="critical")
    except Exception:  # pragma: no cover -- alerting never blocks the halt
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


def _shared_halt_active(min_interval: float = 2.0) -> tuple[str, str] | None:
    """The cluster-wide halt from the shared world store, throttled + fail-open.

    Only engaged on a shared backend (Postgres): the SQLite single-host path is
    already covered by the local HALT file, and querying a per-host SQLite world
    on every tool call would add hot-path cost for no cluster benefit. Returns
    ``(reason, source)`` when armed, else ``None``. Any error -> keep the last
    known state and drop the cached handle so the next check reconnects -- the
    killswitch must never wedge a run on a shared-store hiccup, but a transient
    read error must not silently drop a real halt either.
    """
    global _last_shared_check_ts, _last_shared_halt, _shared_world
    now = time.time()
    if now - _last_shared_check_ts < min_interval:
        return _last_shared_halt
    _last_shared_check_ts = now
    try:
        from .world_model_backends import is_postgres_configured
        if not is_postgres_configured():
            _last_shared_halt = None
            return None
        if _shared_world is None:
            from .world_model import open_world
            _shared_world = open_world()
        state = _shared_world.active_halt()
        _last_shared_halt = (
            (state.get("reason") or "cluster halt", state.get("source") or "shared")
            if state else None
        )
    except Exception:  # pragma: no cover -- fail-open; reconnect next time
        _shared_world = None
    return _last_shared_halt


def check() -> None:
    """Raise ``Halted`` if any halt source is active."""
    with _state_lock:
        ip = _in_process_halt
    if ip is not None:
        raise Halted(ip[0], ip[1])
    if _file_halt_active():
        raise Halted(f"HALT file present at {_halt_file_path()}", "file")
    shared = _shared_halt_active()
    if shared is not None:
        raise Halted(shared[0], shared[1])


def is_active() -> bool:
    """Non-raising query. Useful for UI."""
    try:
        check()
    except Halted:
        return True
    return False
