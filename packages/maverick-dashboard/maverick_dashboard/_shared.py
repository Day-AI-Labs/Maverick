"""Helpers shared by the dashboard's ``app`` and ``api`` modules.

These four symbols lived as verbatim copies in both ``app`` and ``api``.
The duplication was deliberate -- ``app`` imports ``api`` at module load,
so the reverse import would cycle, and the old ``_world`` docstrings said
as much. A third module that imports neither removes the copies without
reintroducing the cycle; both modules ``from ._shared import`` these.
"""
from __future__ import annotations

from typing import Any

# One process-wide WorldModel cache keyed by absolute DB path (was a
# separate dict per module). Tests clear it via ``<module>._world_cache``.
_world_cache: dict[str, Any] = {}

def _any_provider_key_set() -> bool:
    """True iff some LLM provider is configured (env key, base-url env, or
    a ``[providers.<name>]`` config table with api_key/base_url).

    Council UX fix round 1: the dashboard used to hard-fail on a missing
    ANTHROPIC_API_KEY even when the user had OpenAI or Gemini set up.
    Round 2 (platform test): it still rejected keyless self-hosted setups
    (Ollama/vLLM/TGI via config or *_BASE_URL) that the CLI accepted and ran
    fine — three components, three different predicates. Delegate to the one
    shared predicate in maverick.config; the name is kept for call sites.
    """
    try:
        from maverick.config import any_provider_configured
        return any_provider_configured()
    except Exception:  # pragma: no cover -- never block the dashboard on config
        return False


def _world():
    """Return a per-DB-path cached WorldModel (council perf fix).

    Opening a new WorldModel on every request re-runs the PRAGMAs and the
    schema-migration check, leaks the connection (no close()), and
    serialises the asyncio loop because sqlite3 is sync. Cache by absolute
    DB path so test fixtures that monkeypatch ``DEFAULT_DB`` to a fresh
    ``tmp_path`` still get an isolated WorldModel per test.
    """
    # Client binding: when the deployment is bound to a client, the dashboard
    # reads/writes that client's isolated world DB (under tenants/<client>/),
    # never the shared root. Unbound (legacy / tests that monkeypatch
    # DEFAULT_DB) keeps the prior DEFAULT_DB path exactly.
    #
    # Backend selection (split-brain fix): when the deployment opts into Postgres
    # ([world_model] backend = "postgres" / MAVERICK_WORLD_BACKEND=postgres), the
    # dashboard must read/write the SAME Postgres the runner, channel server and
    # gRPC API use. Previously this always opened SQLite, so a Postgres
    # deployment had the dashboard reading a stale local world.db. Checked before
    # the tenant floor because Postgres isolates by tenant_id at query time, not
    # by a per-tenant file. open_postgres_world() builds a fresh connection per
    # call, so cache the one backend for the process under a fixed key.
    from maverick.world_model_backends import is_postgres_configured
    if is_postgres_configured():
        cached = _world_cache.get("__postgres__")
        if cached is None:
            from maverick.world_model import open_world
            cached = open_world()  # also enforces the at-rest fail-closed guard
            _world_cache["__postgres__"] = cached
        return cached
    from maverick.paths import current_tenant_id
    tid = current_tenant_id()
    if tid:
        from maverick.world_model import world_for_tenant
        return world_for_tenant(tid)
    from maverick.world_model import DEFAULT_DB, WorldModel
    key = str(DEFAULT_DB)
    cached = _world_cache.get(key)
    if cached is None:
        cached = WorldModel(DEFAULT_DB)
        _world_cache[key] = cached
    return cached
