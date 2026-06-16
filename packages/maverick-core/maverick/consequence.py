"""The Consequence Engine -- reality as the reward.

Every learning signal in production AI is a proxy: a human saying "looks good"
(RLHF), an LLM judge (RLAIF), or a hardcoded checker (RLVR). None is the *actual
consequence* of the action in the world -- because no one else operates a
governed workforce that acts on real business systems and can observe the
result. Maverick can: weeks later, the invoice gets paid or it doesn't, the
contract renews or it doesn't, the ticket stays closed or it reopens. That
downstream fact is **ground truth** -- the one signal that can't be gamed,
because a policy that fools an LLM judge still fails reality.

This module is the grounded-outcome **join**: a system of record (CRM / ERP /
ticketing) reports a real outcome for a past episode via :func:`record_outcome`,
keyed by the ``(goal_id, episode_id)`` the agent acted under; :func:`resolve`
returns it if it has landed. :func:`grounded_outcome` is the helper the data
engine / causal credit use to **prefer reality over the proxy** wherever reality
has reported back -- so triage and promotion learn from what actually happened,
not from a model's opinion of it.

The per-customer connectors that CALL ``record_outcome`` (map an invoice/contract
id back to the episode that touched it) are integration seams; the grounded join,
the store, and the prefer-reality rule are here. OFF by default: ``record_outcome``
just stores (harmless), and the data-engine join only consults real outcomes when
``[consequence]`` is enabled.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_ROWS = 100_000


def enabled() -> bool:
    """Whether the data-engine join should prefer real outcomes. OFF by default."""
    env = os.environ.get("MAVERICK_CONSEQUENCE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_consequence

        return bool(get_consequence().get("enable", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _clamp(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ConsequenceStore:
    """Append-only store of real-world outcome events, keyed (goal_id, episode_id).

    The latest event for a key wins (a contract can renew, then churn -- the most
    recent ground truth is the reward). Atomic-append, 0600, bounded.
    """

    path: Path | None = None
    max_rows: int = _MAX_ROWS
    _latest: dict = None  # type: ignore[assignment]
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock is None:
            self._lock = threading.Lock()
        if self._latest is None:
            self._latest = {}
        if self.path is not None:
            self._load()

    def record(self, goal_id: int, episode_id: int, value: float, *, kind: str = "",
               ts: float | None = None) -> bool:
        """Append a real outcome for a past episode. Never raises."""
        key = (int(goal_id), int(episode_id))
        row = {"ts": ts if ts is not None else time.time(), "goal_id": key[0],
               "episode_id": key[1], "value": _clamp(value), "kind": str(kind)[:64]}
        with self._lock:
            self._latest[key] = (row["ts"], row["value"])
            if self.path is None:
                return True
            try:
                p = Path(self.path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(os.open(p, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600),
                          "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                return True
            except Exception:  # pragma: no cover -- best-effort
                log.debug("consequence record failed", exc_info=True)
                return False

    def resolve(self, goal_id: int, episode_id: int) -> float | None:
        """The latest real outcome for the episode, or None if none has landed."""
        with self._lock:
            hit = self._latest.get((int(goal_id), int(episode_id)))
            return hit[1] if hit is not None else None

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return
        for raw in lines[-self.max_rows:]:
            try:
                d = json.loads(raw)
                key = (int(d["goal_id"]), int(d["episode_id"]))
                ts = float(d.get("ts", 0.0))
                prev = self._latest.get(key)
                if prev is None or ts >= prev[0]:
                    self._latest[key] = (ts, _clamp(d["value"]))
            except (KeyError, ValueError, TypeError):
                continue


_shared: dict = {}
_shared_lock = threading.Lock()


def shared() -> ConsequenceStore:
    from .paths import data_dir

    path = data_dir("consequences.ndjson")
    with _shared_lock:
        store = _shared.get(path)
        if store is None:
            store = ConsequenceStore(path=path)
            _shared[path] = store
        return store


def reset_shared() -> None:
    with _shared_lock:
        _shared.clear()


def record_outcome(goal_id: int, episode_id: int, value: float, *, kind: str = "",
                   store: ConsequenceStore | None = None) -> bool:
    """Record a real downstream outcome for a past episode (the grounded reward).

    Called by a system-of-record connector once reality reports back. ``value`` is
    the real result in [0, 1] (paid=1.0 / unpaid=0.0, renewed=1.0, reopened=0.0,
    or a graded result). Just stores; the data-engine join decides whether to use
    it (gated by ``[consequence]``)."""
    return (store or shared()).record(goal_id, episode_id, value, kind=kind)


def resolve(goal_id: int, episode_id: int, *, store: ConsequenceStore | None = None) -> float | None:
    """The real outcome for an episode if it has landed, else None."""
    return (store or shared()).resolve(goal_id, episode_id)


def grounded_outcome(goal_id: int, episode_id: int, proxy: float | None, *,
                     store: ConsequenceStore | None = None) -> float | None:
    """Prefer the real outcome over the proxy (verifier confidence) when present.

    The one-line rule that grounds learning in reality: if a real consequence has
    landed for this episode, that's the reward; otherwise fall back to the proxy.
    A no-op (returns ``proxy``) unless ``[consequence]`` is enabled.
    """
    if not enabled():
        return proxy
    real = resolve(goal_id, episode_id, store=store)
    return real if real is not None else proxy


__all__ = [
    "ConsequenceStore", "enabled", "shared", "reset_shared",
    "record_outcome", "resolve", "grounded_outcome",
]
