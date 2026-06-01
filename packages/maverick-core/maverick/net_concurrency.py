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

# Lazily-created per-host semaphores. asyncio.Semaphore (3.10+) doesn't bind
# to a loop at construction, and the agent loop runs gather on a single
# loop, so a module-level registry is safe.
_semaphores: dict[str, asyncio.Semaphore] = {}


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
    _semaphores.clear()


__all__ = ["host_key", "limit"]
