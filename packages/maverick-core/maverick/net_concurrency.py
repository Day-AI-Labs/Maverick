"""Per-host concurrency caps for parallel network-read tools (#434).

The agent loop runs a turn's ``parallel_safe`` tool calls concurrently
(asyncio.gather). Idempotent network reads (http_fetch, arxiv, wikipedia,
semantic_scholar, hackernews) are parallel_safe, so a turn that fans out
many reads to the SAME host can hammer it / trip rate limits. This module
gates each network read behind a per-host asyncio.Semaphore so same-host
reads are throttled while cross-host reads stay fully concurrent.

Local reads (read_file / list_dir / repo_map / dep_graph) have no host key
and are never gated. Unknown tools return no host key too, so this is a
strict refinement: anything it doesn't recognise behaves exactly as before.

Tunable: ``MAVERICK_NET_HOST_CONCURRENCY`` (default 4). 0 or negative
disables gating entirely.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from urllib.parse import urlparse

# Tools whose endpoint host is fixed (not derivable from args). Mapping the
# tool name to a stable host key is enough to serialise same-service fanout.
_FIXED_HOST_TOOLS = {
    "arxiv": "arxiv.org",
    "wikipedia": "wikipedia.org",
    "semantic_scholar": "semanticscholar.org",
    "hackernews": "ycombinator-hn",
}

# Lazily-created per-host semaphores for the CURRENT event loop. A Semaphore
# binds to a loop the first time it is awaited, so reusing a module-level one
# across loops -- a second asyncio.run(), the dashboard's loop, a worker
# thread's loop -- raised "bound to a different loop" and broke same-host
# fetches. We remember which loop the registry belongs to (by identity, so a
# recycled id() can't alias a dead loop) and rebuild it when the loop changes.
_semaphores: dict[str, asyncio.Semaphore] = {}
_sem_loop: asyncio.AbstractEventLoop | None = None


def _cap() -> int:
    try:
        return int(os.environ.get("MAVERICK_NET_HOST_CONCURRENCY", "4"))
    except ValueError:
        return 4


def host_key(tool_name: str, args: dict) -> str | None:
    """Return a stable per-host key for a network tool call, or None.

    None means "don't gate" — local/unknown tools, or a URL we can't parse.
    """
    if tool_name == "http_fetch":
        url = (args or {}).get("url") or ""
        try:
            host = urlparse(url).hostname
        except (ValueError, TypeError):
            return None
        return f"http:{host.lower()}" if host else None
    fixed = _FIXED_HOST_TOOLS.get(tool_name)
    return f"svc:{fixed}" if fixed else None


def _get_semaphore(key: str, cap: int) -> asyncio.Semaphore:
    global _sem_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - limit() is only used under a loop
        loop = None
    if loop is not _sem_loop:
        # The active event loop changed; semaphores bound to the previous loop
        # can't be awaited here. Start a fresh registry for this loop.
        _semaphores.clear()
        _sem_loop = loop
    sem = _semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(cap)
        _semaphores[key] = sem
    return sem


def limit(tool_name: str, args: dict):
    """Async context manager that caps concurrency for a tool's host.

    Returns a no-op context for non-network/unknown tools or when gating is
    disabled (cap <= 0), so callers can wrap unconditionally.
    """
    cap = _cap()
    if cap <= 0:
        return contextlib.nullcontext()
    key = host_key(tool_name, args)
    if key is None:
        return contextlib.nullcontext()
    return _get_semaphore(key, cap)


def _reset_for_tests() -> None:
    """Clear the semaphore registry (tests that vary the cap)."""
    global _sem_loop
    _semaphores.clear()
    _sem_loop = None


__all__ = ["host_key", "limit"]
