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

**Warm-on-start** (default OFF): with ``[tools] output_cache_snapshot = true``
(or ``MAVERICK_TOOL_CACHE_SNAPSHOT=1``), the cache persists entries to a JSONL
snapshot under ``~/.maverick/`` and reloads the still-fresh ones on the first
lookup of the next process, so a rerun starts with yesterday's repo_map instead
of a cold cache. Entries carry a wall-clock stamp; TTL is re-checked at load.

Thread-safe; lookups/stores never raise into the tool path.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

_DEFAULT_SIZE = 256
_lock = threading.Lock()
# key -> (value, stored_at_monotonic, stored_at_epoch)
_store: OrderedDict[str, tuple[str, float, float]] = OrderedDict()
_hits = 0
_misses = 0
_warmed = False


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


def snapshot_enabled() -> bool:
    """Whether warm-on-start snapshot persistence is on (default OFF)."""
    if _env_true("MAVERICK_TOOL_CACHE_SNAPSHOT"):
        return True
    return bool(_cfg().get("output_cache_snapshot", False))


def _snapshot_path() -> Path:
    env = os.environ.get("MAVERICK_TOOL_CACHE_SNAPSHOT_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".maverick" / "tool_cache_snapshot.jsonl"


def save_snapshot() -> int:
    """Persist current entries to the snapshot file. Returns entries written.

    Values are stored with their wall-clock stamp so the next process can
    re-apply the TTL. Best-effort: any I/O problem is swallowed (the cache
    must never break the tool path) and 0 is returned.
    """
    if not snapshot_enabled():
        return 0
    try:
        path = _snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            rows = [(k, v, epoch) for k, (v, _mono, epoch) in _store.items()]
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for k, v, epoch in rows:
                fh.write(json.dumps({"k": k, "v": v, "t": epoch}) + "\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return len(rows)
    except Exception:  # pragma: no cover -- snapshot is best-effort
        return 0


def warm_on_start() -> int:
    """Load still-fresh snapshot entries into the cache. Returns entries loaded.

    Idempotent per process (the first call wins). TTL is enforced against the
    entry's wall-clock stamp; expired rows are skipped. Capped at the
    configured cache size. Best-effort: a missing/corrupt snapshot loads 0.
    """
    global _warmed
    with _lock:
        if _warmed:
            return 0
        _warmed = True
    if not (enabled() and snapshot_enabled()):
        return 0
    try:
        path = _snapshot_path()
        if not path.exists():
            return 0
        ttl = _ttl_s()
        now_epoch = time.time()
        now_mono = time.monotonic()
        cap = _maxsize()
        loaded = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    k, v, epoch = str(row["k"]), str(row["v"]), float(row["t"])
                except (ValueError, TypeError, KeyError):
                    continue  # tolerate a corrupt / partial line
                age = max(0.0, now_epoch - epoch)
                if ttl and age > ttl:
                    continue
                with _lock:
                    if len(_store) >= cap:
                        break
                    # Backdate the monotonic stamp so the remaining TTL is right.
                    _store[k] = (v, now_mono - age, epoch)
                    loaded += 1
        return loaded
    except Exception:  # pragma: no cover -- warm is best-effort
        return 0


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
    if not _warmed:
        warm_on_start()
    name = getattr(tool, "name", "")
    k = _key(name, args)
    ttl = _ttl_s()
    with _lock:
        entry = _store.get(k)
        if entry is None:
            _misses += 1
            return (False, None)
        value, stored_at, _epoch = entry
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
        _store[k] = (value, time.monotonic(), time.time())
        _store.move_to_end(k)
        while len(_store) > cap:
            _store.popitem(last=False)  # evict least-recently-used


def stats() -> dict[str, int]:
    """``{hits, misses, size}`` — for the dashboard / tests."""
    with _lock:
        return {"hits": _hits, "misses": _misses, "size": len(_store)}


def reset() -> None:
    """Clear the cache and counters (tests / a fresh run)."""
    global _hits, _misses, _warmed
    with _lock:
        _store.clear()
        _hits = 0
        _misses = 0
        _warmed = False


def purge(tool_name: str | None = None) -> int:
    """Drop cached entries -- all of them, or just those for ``tool_name``.

    Returns the number of entries removed. Unlike :func:`reset`, the hit/miss
    counters are left intact, so a targeted purge (e.g. after a tool's
    underlying data changed) doesn't throw away the run's hit-rate history.
    """
    with _lock:
        if tool_name:
            prefix = f"{tool_name}:"
            keys = [k for k in _store if k.startswith(prefix)]
            for k in keys:
                del _store[k]
            return len(keys)
        n = len(_store)
        _store.clear()
        return n


__all__ = [
    "enabled", "cacheable", "get_cached", "store_cached", "stats", "reset",
    "snapshot_enabled", "save_snapshot", "warm_on_start",
]
