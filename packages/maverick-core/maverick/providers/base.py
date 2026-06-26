"""Provider interface marker.

The Maverick provider contract is structural (duck-typed): any object
with ``complete()`` and ``complete_async()`` methods that take the
Anthropic-format system/messages/tools and return ``LLMResponse``
works. This module exists as a documentation anchor; new providers
don't need to inherit from anything.
"""
from __future__ import annotations

import contextvars
from collections.abc import Callable
from typing import Any, Protocol

from ..budget import Budget
from ..llm import LLMResponse

# Per-context sampling-temperature override. Best-of-N sets this per attempt so
# each re-roll samples at a different temperature. A ContextVar -- not a process
# -global env var -- so concurrent goals on one process never read each other's
# temperature (the old os.environ["MAVERICK_TEMPERATURE"] approach raced). It is
# copied across ``asyncio.to_thread``, so a sync provider running in a worker
# thread still sees the value bound by the awaiting goal task.
_sampling_temperature: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "maverick_sampling_temperature", default=None,
)


def sampling_temperature() -> float | None:
    """The sampling temperature bound to the current context, or None."""
    return _sampling_temperature.get()


def set_sampling_temperature(value: float | None) -> contextvars.Token:
    """Bind the sampling temperature for the current context; returns a token to
    pass to :func:`reset_sampling_temperature`."""
    return _sampling_temperature.set(value)


def reset_sampling_temperature(token: contextvars.Token) -> None:
    """Restore the temperature bound before ``set_sampling_temperature``."""
    try:
        _sampling_temperature.reset(token)
    except (ValueError, LookupError):  # pragma: no cover -- stale/cross-context token
        _sampling_temperature.set(None)


def llm_http_timeout() -> Any | None:
    """Bounded HTTP timeout for provider SDK clients.

    Without this the anthropic/openai SDKs use a ~10-min per-request
    default, so a hung/half-open connection pins one of the few
    concurrency slots until it expires (and across retries). ``read`` is
    httpx's per-chunk timeout, not a total cap, so long *streamed*
    generations are unaffected — only genuinely stalled sockets trip it.
    Returns None (SDK default) if httpx isn't importable.
    """
    try:
        import httpx

        from .._envparse import env_float
        return httpx.Timeout(
            env_float("MAVERICK_LLM_READ_TIMEOUT", 120.0),
            connect=env_float("MAVERICK_LLM_CONNECT_TIMEOUT", 15.0),
        )
    except Exception:
        return None


class Provider(Protocol):
    """Structural type for a provider client."""

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse: ...

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse: ...


__all__ = ["Provider", "llm_http_timeout"]
