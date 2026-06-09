"""Helpers shared by the dashboard's ``app`` and ``api`` modules.

These four symbols lived as verbatim copies in both ``app`` and ``api``.
The duplication was deliberate -- ``app`` imports ``api`` at module load,
so the reverse import would cycle, and the old ``_world`` docstrings said
as much. A third module that imports neither removes the copies without
reintroducing the cycle; both modules ``from ._shared import`` these.
"""
from __future__ import annotations

import os
from typing import Any

# One process-wide WorldModel cache keyed by absolute DB path (was a
# separate dict per module). Tests clear it via ``<module>._world_cache``.
_world_cache: dict[str, Any] = {}

_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
)


def _any_provider_key_set() -> bool:
    """True iff at least one supported provider's env var is populated.

    Council UX fix: the dashboard used to hard-fail on a missing
    ANTHROPIC_API_KEY even when the user had OpenAI or Gemini set up.
    """
    return any(os.environ.get(v) for v in _PROVIDER_ENV_VARS)


def _world():
    """Return a per-DB-path cached WorldModel (council perf fix).

    Opening a new WorldModel on every request re-runs the PRAGMAs and the
    schema-migration check, leaks the connection (no close()), and
    serialises the asyncio loop because sqlite3 is sync. Cache by absolute
    DB path so test fixtures that monkeypatch ``DEFAULT_DB`` to a fresh
    ``tmp_path`` still get an isolated WorldModel per test.
    """
    from maverick.world_model import DEFAULT_DB, WorldModel
    key = str(DEFAULT_DB)
    cached = _world_cache.get(key)
    if cached is None:
        cached = WorldModel(DEFAULT_DB)
        _world_cache[key] = cached
    return cached
