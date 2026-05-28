"""Provider interface marker.

The Maverick provider contract is structural (duck-typed): any object
with ``complete()`` and ``complete_async()`` methods that take the
Anthropic-format system/messages/tools and return ``LLMResponse``
works. This module exists as a documentation anchor; new providers
don't need to inherit from anything.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from ..budget import Budget
from ..llm import LLMResponse


def llm_http_timeout() -> Optional[Any]:
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
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse: ...

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse: ...


__all__ = ["Provider", "llm_http_timeout"]
