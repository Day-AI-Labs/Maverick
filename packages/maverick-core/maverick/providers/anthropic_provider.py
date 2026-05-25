"""Anthropic provider. The full v0.1 implementation lives in ``maverick.llm``;
this class is a thin shim over it for the provider registry.

The planned refactor moves the Anthropic-specific logic here and reduces
``maverick.llm.LLM`` to a dispatcher over the registry.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import Provider, ProviderResponse


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        # Lazy import keeps the module loadable without the anthropic SDK.
        from ..llm import LLM

        self._llm = LLM(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> ProviderResponse:
        resp = await self._llm.complete_async(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            model=model,
        )
        usage = resp.raw.usage
        return ProviderResponse(
            text=resp.text,
            thinking=resp.thinking,
            tool_calls=resp.tool_calls,
            stop_reason=resp.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=resp.cache_creation_tokens,
            cache_read_tokens=resp.cache_read_tokens,
            raw=resp.raw,
        )

    def pricing(self, model: str) -> tuple[float, float]:
        from ..llm import MODEL_PRICES

        return MODEL_PRICES.get(model, (3.0, 15.0))
