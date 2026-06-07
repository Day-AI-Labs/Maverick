"""Provider failover (opt-in, default OFF).

Declare fallback model chains so a transient provider failure auto-switches to
the next model instead of failing the call. Off by default; configure::

    [provider_failover]
    chains = { "anthropic:claude-opus-4-8" = ["openai:gpt-4.1", "gemini:gemini-2"] }

The core `failover` / `afailover` helpers are pure "try each until success" over
callables, unit-tested with mocks; `fallback_models` reads the config (returns []
when unset -> failover is a no-op). Wiring lives in `LLM.complete` /
`complete_async`, which skip all of this entirely when no chain is configured.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def fallback_models(primary: str) -> list[str]:
    """Configured fallback chain for ``primary`` (``[]`` when failover is off)."""
    try:
        from .config import load_config
        chains = ((load_config() or {}).get("provider_failover") or {}).get("chains") or {}
        fb = chains.get(primary)
        if isinstance(fb, list):
            return [str(m) for m in fb if str(m) and str(m) != primary]
    except Exception:  # pragma: no cover -- never block a call on a config error
        pass
    return []


def failover(attempts, *, should_retry=None):
    """Call each ``(label, thunk)`` in order; return the first success.

    On exception, log and try the next — unless ``should_retry(exc)`` is False
    (then re-raise immediately, e.g. for a budget/egress error that another model
    won't fix). Re-raises the last exception if all fail. Empty -> ValueError."""
    attempts = list(attempts)
    if not attempts:
        raise ValueError("failover: no attempts")
    last: Exception | None = None
    for label, thunk in attempts:
        try:
            return thunk()
        except Exception as e:  # noqa: BLE001 -- failover boundary
            last = e
            if should_retry is not None and not should_retry(e):
                raise
            log.warning("provider failover: %s failed (%s); trying next",
                        label, type(e).__name__)
    assert last is not None
    raise last


async def afailover(attempts, *, should_retry=None):
    """Async `failover`: each thunk returns an awaitable; return the first success."""
    attempts = list(attempts)
    if not attempts:
        raise ValueError("failover: no attempts")
    last: Exception | None = None
    for label, thunk in attempts:
        try:
            return await thunk()
        except Exception as e:  # noqa: BLE001 -- failover boundary
            last = e
            if should_retry is not None and not should_retry(e):
                raise
            log.warning("provider failover: %s failed (%s); trying next",
                        label, type(e).__name__)
    assert last is not None
    raise last


__all__ = ["fallback_models", "failover", "afailover"]
