"""Provider interface marker.

The Maverick provider contract is structural (duck-typed): any object
with ``complete()`` and ``complete_async()`` methods that take the
Anthropic-format system/messages/tools and return ``LLMResponse``
works. This module exists as a documentation anchor; new providers
don't need to inherit from anything.
"""
from __future__ import annotations

from typing import Optional, Protocol

from ..budget import Budget
from ..llm import LLMResponse


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


__all__ = ["Provider"]
