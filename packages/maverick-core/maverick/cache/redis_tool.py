"""Distributed tool-output cache backend on Redis (roadmap: 2027 H2 performance).

:mod:`maverick.tool_cache` memoizes side-effect-free tool results per
*process*: every worker in a fleet pays its own cold start for the same
repo_map / read_file / dep_graph calls. This backend gives the cache
cross-process and cross-host reach by keeping entries in Redis, so the second
worker on a repo starts warm.

It deliberately mirrors ``tool_cache``'s semantics rather than inventing new
ones: only string values; ``ERROR:``-prefixed results are never stored (a
transient failure must not be pinned); TTL bounds staleness (``SETEX`` when a
TTL is set, plain ``SET`` otherwise); and — crucially — the *same key
canonicalization*: ``tool_cache._key`` is imported and reused, so the local
and distributed caches agree on call identity. Keys live under a namespace
prefix (default ``mvk:toolcache``) so :meth:`purge` and :meth:`stats` can
SCAN only our keys on a shared Redis.

Fail-open, always: a cache must never break the tool path. ANY redis error in
``get``/``store`` — connection refused, auth, timeout, even the ``redis``
package missing — logs at debug and behaves as a miss / no-op; the tool just
runs. The client import is lazy and comes from the existing ``redis`` extra:
``pip install 'maverick-agent[redis]'``.

Default OFF and never auto-imported by ``tool_cache`` — the caller wires it::

    [tools]
    output_cache_backend = "redis"            # env MAVERICK_TOOL_CACHE_BACKEND wins
    output_cache_redis_url = "redis://..."    # env MAVERICK_TOOL_CACHE_REDIS_URL wins
    output_cache_ttl_s = 600                  # shared with the local cache

``enabled()`` answers "did the operator pick the redis backend?";
``from_config()`` builds the configured instance (or ``None``).

Status: EXPERIMENTAL — this backend is implemented and unit-tested but **not yet
wired into the live tool cache** (``maverick.cache.tool`` consults no backend
selection, and nothing calls :func:`enabled` / :func:`from_config` in a
production path). Setting ``[tools] output_cache_backend = "redis"`` therefore
has no effect today; a caller must be added to ``cache.tool`` first.
"""
from __future__ import annotations

import logging
import os

from .tool import _key  # reuse: identical call identity to the local cache

log = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "mvk:toolcache"
DEFAULT_URL = "redis://localhost:6379/0"
_SCAN_COUNT = 500  # SCAN hint / DEL chunk size: bounded round-trips on big caches


class RedisToolCache:
    """Tool-output cache entries in Redis; same semantics as ``tool_cache``.

    ``ttl_s=None`` (or 0) means no expiry, matching the local cache's
    ``output_cache_ttl_s = 0``. ``namespace`` prefixes every key.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        ttl_s: float | None = None,
        namespace: str = DEFAULT_NAMESPACE,
    ):
        self.url = (url or "").strip() or DEFAULT_URL
        self.ttl_s = float(ttl_s) if ttl_s else None
        self.namespace = str(namespace).rstrip(":") or DEFAULT_NAMESPACE
        self._cli = None
        self._hits = 0
        self._misses = 0

    def _client(self):
        if self._cli is None:
            import redis  # lazy -- the `redis` extra: pip install 'maverick-agent[redis]'
            self._cli = redis.Redis.from_url(self.url, decode_responses=True)
        return self._cli

    def _redis_key(self, tool_name: str, args: dict) -> str:
        return f"{self.namespace}:{_key(tool_name, args)}"

    def get(self, tool_name: str, args: dict) -> tuple[bool, str | None]:
        """Return ``(hit, value)``; any redis trouble is a miss, never a raise."""
        try:
            value = self._client().get(self._redis_key(tool_name, args))
        except Exception as exc:
            log.debug("redis tool cache: get failed, treating as miss (%s)", exc)
            self._misses += 1
            return (False, None)
        if value is None:
            self._misses += 1
            return (False, None)
        if isinstance(value, bytes):  # a client without decode_responses
            value = value.decode("utf-8", "replace")
        self._hits += 1
        return (True, value)

    def store(self, tool_name: str, args: dict, value: str) -> None:
        """Store a successful result; errors and non-strings are never cached.

        ``SETEX`` when a TTL is configured, plain ``SET`` otherwise. Any redis
        trouble is a logged no-op.
        """
        if not isinstance(value, str) or value.startswith("ERROR:"):
            return  # mirror tool_cache: never pin a failure
        try:
            key = self._redis_key(tool_name, args)
            if self.ttl_s:
                self._client().setex(key, max(1, int(self.ttl_s)), value)
            else:
                self._client().set(key, value)
        except Exception as exc:
            log.debug("redis tool cache: store failed, skipping (%s)", exc)

    def purge(self, tool_name: str | None = None) -> int:
        """Delete our namespace's entries (optionally one tool's). Returns count.

        SCAN+DEL scoped to the namespace prefix so a shared Redis is safe —
        never FLUSHDB. Fail-open: errors log and return 0.
        """
        pattern = (
            f"{self.namespace}:{tool_name}:*" if tool_name else f"{self.namespace}:*"
        )
        try:
            cli = self._client()
            keys = list(cli.scan_iter(match=pattern, count=_SCAN_COUNT))
            for i in range(0, len(keys), _SCAN_COUNT):
                chunk = keys[i:i + _SCAN_COUNT]
                if chunk:
                    cli.delete(*chunk)
            return len(keys)
        except Exception as exc:
            log.debug("redis tool cache: purge failed (%s)", exc)
            return 0

    def stats(self) -> dict[str, int]:
        """``{hits, misses, size}`` — local process counters plus the
        namespace-scoped key count (SCAN, not DBSIZE: the db may be shared)."""
        size = 0
        try:
            for _ in self._client().scan_iter(match=f"{self.namespace}:*", count=_SCAN_COUNT):
                size += 1
        except Exception as exc:
            log.debug("redis tool cache: stats scan failed (%s)", exc)
        return {"hits": self._hits, "misses": self._misses, "size": size}


def _tools_cfg() -> dict:
    try:
        from ..config import load_config
        return (load_config() or {}).get("tools", {}) or {}
    except Exception:  # pragma: no cover -- config never blocks the tool path
        return {}


def enabled() -> bool:
    """Whether the operator selected the redis backend (default OFF).

    ``MAVERICK_TOOL_CACHE_BACKEND=redis`` (env wins) or
    ``[tools] output_cache_backend = "redis"``.
    """
    backend = os.environ.get("MAVERICK_TOOL_CACHE_BACKEND", "").strip().lower()
    if not backend:
        backend = str(_tools_cfg().get("output_cache_backend", "")).strip().lower()
    return backend == "redis"


def from_config() -> RedisToolCache | None:
    """The configured cache instance, or ``None`` when the backend is off.

    URL: ``MAVERICK_TOOL_CACHE_REDIS_URL`` (env wins) or
    ``[tools] output_cache_redis_url``; TTL reuses the local cache's
    ``[tools] output_cache_ttl_s`` so both tiers expire together.
    """
    if not enabled():
        return None
    cfg = _tools_cfg()
    url = os.environ.get("MAVERICK_TOOL_CACHE_REDIS_URL", "").strip()
    if not url:
        url = str(cfg.get("output_cache_redis_url", "") or "").strip()
    try:
        ttl = max(0.0, float(cfg.get("output_cache_ttl_s", 0)))
    except (TypeError, ValueError):
        ttl = 0.0
    return RedisToolCache(url or None, ttl_s=ttl or None)


__all__ = ["DEFAULT_NAMESPACE", "RedisToolCache", "enabled", "from_config"]
