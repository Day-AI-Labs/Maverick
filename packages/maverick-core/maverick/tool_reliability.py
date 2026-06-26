"""Shared reliability policy for tool dispatch.

~80 tools are thin API wrappers with no retry/backoff of their own. Rather
than make each author hand-roll a retry loop, ``ToolRegistry.run`` routes
every call through this one policy:

  * Only genuinely *transient* upstream failures are retried -- rate limits,
    network errors, and 5xx -- reusing the classified backoff the LLM path
    already uses (``retry_classifier``). A generic tool exception (bad args,
    missing file, a logic bug) classifies as UNKNOWN and is **not** retried:
    re-running a deterministic failure just burns budget and wall-clock.
  * Only low/medium-risk tools are auto-retried. High-risk tools (writes,
    payments, messaging, infra, device control, spawn -- per
    ``safety.tool_risk``) run exactly once: a transient error raised *after*
    a partial side-effect must never be silently re-fired.

Fail-open: the risk lookup never blocks a call, and a non-retryable error or
tool re-raises so the registry keeps its own error-to-string handling.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .retry import classifier as retry_classifier

log = logging.getLogger(__name__)

T = TypeVar("T")

# Classes that mean "the upstream was flaky", not "this call is wrong". A
# deterministic tool error (UNKNOWN/MALFORMED/AUTH/...) is left to the caller.
_RETRYABLE = frozenset({
    retry_classifier.ErrorClass.RATE_LIMIT,
    retry_classifier.ErrorClass.TRANSIENT_NETWORK,
    retry_classifier.ErrorClass.SERVER_5XX,
})


def is_retry_safe(name: str) -> bool:
    """Whether a tool may be auto-retried on a transient failure.

    Keyed off the existing per-tool risk tier: low/medium tools are reads /
    lookups / queries (idempotent enough to re-fire); high-risk tools mutate
    external state and must not be retried automatically. Unknown / errored
    classification is treated conservatively as not-retry-safe.
    """
    try:
        from .safety.tool_risk import tool_risk
        return tool_risk(name) != "high"
    except Exception:  # pragma: no cover -- classification never blocks a call
        return False


async def run_with_retry(name: str, call: Callable[[], Awaitable[T]]) -> T:
    """Invoke ``call`` (a zero-arg awaitable factory), retrying transient
    failures for retry-safe tools.

    Re-raises the last exception when retries are exhausted, the error isn't
    transient, or the tool isn't retry-safe -- the caller keeps its own
    error handling.
    """
    if not is_retry_safe(name):
        return await call()
    attempts = 0
    while True:
        try:
            return await call()
        except Exception as e:
            klass = retry_classifier.classify(e)
            if klass not in _RETRYABLE or not retry_classifier.should_retry(
                e, attempts_so_far=attempts
            ):
                raise
            delay = retry_classifier.next_delay(e, attempts_so_far=attempts)
            attempts += 1
            log.warning(
                "tool %s transient failure (%s); retry %d in %.1fs",
                name, klass.value, attempts, delay,
            )
            await asyncio.sleep(delay)


__all__ = ["is_retry_safe", "run_with_retry"]
