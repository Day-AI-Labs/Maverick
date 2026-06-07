"""Tool-output cache: memoize side-effect-free tool calls within a process.

Default OFF. When enabled, the result of a *read-only* tool call — one whose
``Tool.parallel_safe`` is ``True`` (repo_map, read_file, list_dir, dep_graph,
...) — is memoized keyed on ``(tool_name, canonical(args))``. A bounded LRU keeps
memory flat; an optional TTL bounds staleness. Tools that write the workspace,
shell out, send a message, or otherwise have side effects are *never* cached
(``parallel_safe`` is the same invariant the agent loop uses to decide a tool is
safe to run concurrently). Error results (``ERROR: ...``) are never cached so a
transient failure is not pinned.

Enable with ``MAVERICK_TOOL_CACHE=1`` or ``[tools] output_cache = true``. Tune
with ``[tools] output_cache_size`` (entries, default 256) and
``[tools] output_cache_ttl_s`` (seconds, 0 = no expiry, default 0).

Thread-safe; lookups/stores never raise into the tool path.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

_DEFAULT_SIZE = 256
_lock = threading.Lock()
# key -> (value, stored_at_monotonic)
_store: OrderedDict[str, tuple[str, float]] = OrderedDict()
_hits = 0
_misses = 0


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _cfg() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("tools", {}) or {}
    except Exception:  # pragma: no cover -- config never blocks the cache
        return {}


def enabled() -> bool:
    """Whether the tool-output cache is on (default OFF)."""
    if _env_true("MAVERICK_TOOL_CACHE"):
        return True
    return bool(_cfg().get("output_cache", False))


def _maxsize() -> int:
    try:
        n = int(_cfg().get("output_cache_size", _DEFAULT_SIZE))
        return n if n > 0 else _DEFAULT_SIZE
    except (TypeError, ValueError):
        return _DEFAULT_SIZE


def _ttl_s() -> float:
    try:
        return max(0.0, float(_cfg().get("output_cache_ttl_s", 0)))
    except (TypeError, ValueError):
        return 0.0


def cacheable(tool: Any) -> bool:
    """Only side-effect-free (``parallel_safe``) tools may be memoized."""
    return getattr(tool, "parallel_safe", False) is True


def _key(tool_name: str, args: dict[str, Any]) -> str:
    try:
        canon = json.dumps(args or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canon = repr(args)
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]
    return f"{tool_name}:{digest}"


def get_cached(tool: Any, args: dict[str, Any]) -> tuple[bool, str | None]:
    """Return ``(hit, value)``. ``(False, None)`` when disabled / not cacheable /
    missing / expired."""
    global _hits, _misses
    if not enabled() or not cacheable(tool):
        return (False, None)
    name = getattr(tool, "name", "")
    k = _key(name, args)
    ttl = _ttl_s()
    with _lock:
        entry = _store.get(k)
        if entry is None:
            _misses += 1
            return (False, None)
        value, stored_at = entry
        if ttl and (time.monotonic() - stored_at) > ttl:
            del _store[k]
            _misses += 1
            return (False, None)
        _store.move_to_end(k)  # LRU bump
        _hits += 1
        return (True, value)


def store_cached(tool: Any, args: dict[str, Any], value: str) -> None:
    """Memoize a successful, non-error result for a cacheable tool."""
    if not enabled() or not cacheable(tool):
        return
    if not isinstance(value, str) or value.startswith("ERROR:"):
        return
    name = getattr(tool, "name", "")
    k = _key(name, args)
    cap = _maxsize()
    with _lock:
        _store[k] = (value, time.monotonic())
        _store.move_to_end(k)
        while len(_store) > cap:
            _store.popitem(last=False)  # evict least-recently-used


def stats() -> dict[str, int]:
    """``{hits, misses, size}`` — for the dashboard / tests."""
    with _lock:
        return {"hits": _hits, "misses": _misses, "size": len(_store)}


def reset() -> None:
    """Clear the cache and counters (tests / a fresh run)."""
    global _hits, _misses
    with _lock:
        _store.clear()
        _hits = 0
        _misses = 0


__all__ = [
    "enabled", "cacheable", "get_cached", "store_cached", "stats", "reset",
]
