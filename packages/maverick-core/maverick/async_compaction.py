"""Async compaction (roadmap: 2027 H1 performance).

Compaction quality costs latency exactly where it hurts — at the start of a
turn, while the user waits. The fix is structural: a conversation's history is
a *stable prefix* plus a couple of fresh turns, so the expensive part (ranking
and trimming the long prefix) can be precomputed in the background between
turns. On the hot path we then compact ``compact(prefix_result + tail)``,
which is cheap because the prefix is already at budget.

Shape:

* ``compact_with_precompute(key, messages, target_tokens)`` — the hot-path
  call. If a background-precomputed prefix matching ``messages`` exists, use
  it (cheap tail-merge); otherwise compact inline (first turn / cold start).
  Either way, schedule a background refresh for the *current* window so the
  next turn hits.
* One daemon worker thread, last-write-wins per key, bounded queue — a slow
  compaction can never back up the agent. Tests inject a synchronous executor.

Opt-in via ``[context] async_compaction = true`` (or
``MAVERICK_ASYNC_COMPACTION=1``) on top of ``[context] compact``; when off,
nothing here is imported by the hot path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable

from . import context_compactor as _cc
from .config import env_flag

log = logging.getLogger(__name__)

# Fresh turns kept OUT of the precomputed prefix (they change every turn).
TAIL_TURNS = 4
_MAX_KEYS = 256


def enabled() -> bool:
    if env_flag("MAVERICK_ASYNC_COMPACTION"):
        return True
    try:
        from .config import load_config
        return bool((load_config() or {}).get("context", {}).get("async_compaction", False))
    except Exception:  # pragma: no cover -- config never blocks the hot path
        return False


def _fingerprint(messages: list[dict]) -> str:
    try:
        canon = json.dumps(messages, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canon = repr(messages)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]


class _Precomputed:
    __slots__ = ("prefix_len", "fingerprint", "messages")

    def __init__(self, prefix_len: int, fingerprint: str, messages: list[dict]):
        self.prefix_len = prefix_len
        self.fingerprint = fingerprint
        self.messages = messages


class BackgroundCompactor:
    """Single-worker precompute cache for compacted conversation prefixes."""

    def __init__(self, executor: Callable[[Callable[[], None]], None] | None = None):
        self._lock = threading.Lock()
        self._cache: dict[str, _Precomputed] = {}
        # Pending keys (last-write-wins): key -> (prefix, target_tokens)
        self._pending: dict[str, tuple[list[dict], int]] = {}
        self._executor = executor
        self._worker: threading.Thread | None = None
        self._wake = threading.Event()

    # -- worker plumbing ------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._executor is not None:
            return
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._drain, name="maverick-async-compaction", daemon=True)
                self._worker.start()

    def _drain(self) -> None:
        while True:
            self._wake.wait(timeout=60.0)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._pending:
                        break
                    key, (prefix, target) = next(iter(self._pending.items()))
                    del self._pending[key]
                self._compute(key, prefix, target)

    def _compute(self, key: str, prefix: list[dict], target_tokens: int) -> None:
        try:
            result = _cc.compact(prefix, target_tokens=target_tokens).messages
        except Exception:  # a compactor bug must never kill the worker
            log.exception("async compaction failed for %s", key)
            return
        with self._lock:
            self._cache[key] = _Precomputed(len(prefix), _fingerprint(prefix), result)
            while len(self._cache) > _MAX_KEYS:
                self._cache.pop(next(iter(self._cache)))

    def _schedule(self, key: str, prefix: list[dict], target_tokens: int) -> None:
        if not prefix:
            return
        with self._lock:
            self._pending[key] = (list(prefix), target_tokens)
            # Bound the queue like the result cache: a burst of distinct
            # conversation keys must not grow it without limit (each entry holds
            # a prefix copy). Precompute is best-effort, so dropping the oldest
            # pending entry just defers that compaction to the on-demand path.
            while len(self._pending) > _MAX_KEYS:
                self._pending.pop(next(iter(self._pending)))
        if self._executor is not None:
            # Test seam: run synchronously through the injected executor.
            with self._lock:
                pending = dict(self._pending)
                self._pending.clear()
            for k, (p, t) in pending.items():
                self._executor(lambda k=k, p=p, t=t: self._compute(k, p, t))
        else:
            self._ensure_worker()
            self._wake.set()

    # -- hot path ---------------------------------------------------------

    def compact_with_precompute(
        self, key: str, messages: list[dict], *, target_tokens: int,
    ) -> list[dict]:
        """Compact ``messages`` using the precomputed prefix when it matches."""
        key = str(key)
        prefix_len = max(0, len(messages) - TAIL_TURNS)
        prefix, tail = messages[:prefix_len], messages[prefix_len:]

        hit: _Precomputed | None = None
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None and cached.prefix_len == prefix_len \
                and cached.fingerprint == _fingerprint(prefix):
            hit = cached

        if hit is not None:
            # Cheap: the prefix is already at budget; merge in the fresh tail.
            out = _cc.compact(list(hit.messages) + tail, target_tokens=target_tokens).messages
        else:
            out = _cc.compact(messages, target_tokens=target_tokens).messages

        # Refresh for the next turn (its prefix is the current full window
        # minus the tail it will grow).
        self._schedule(key, prefix, target_tokens)
        return out

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"cached_keys": len(self._cache), "pending": len(self._pending)}


_shared: BackgroundCompactor | None = None
_shared_lock = threading.Lock()


def shared() -> BackgroundCompactor:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = BackgroundCompactor()
        return _shared


def compact_with_precompute(key: str, messages: list[dict], *, target_tokens: int) -> list[dict]:
    """Module-level convenience over the process-shared compactor."""
    return shared().compact_with_precompute(key, messages, target_tokens=target_tokens)


__all__ = ["enabled", "BackgroundCompactor", "shared", "compact_with_precompute",
           "TAIL_TURNS"]
