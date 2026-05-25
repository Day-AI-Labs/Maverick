"""OpenRouter provider — stub.

OpenRouter is a single endpoint that proxies 200+ models from many
vendors. Planned implementation reuses the OpenAI provider with a
different base_url, since the API is OpenAI-compatible.
"""
from __future__ import annotations

from typing import Optional

from .base import Provider, ProviderResponse


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url or "https://openrouter.ai/api/v1"

    async def complete_async(self, system, messages, tools=None, max_tokens=4096,
                             thinking_budget=None, model=None) -> ProviderResponse:
        raise NotImplementedError(
            "OpenRouterProvider is not yet implemented. Use the Anthropic "
            "provider for now — OpenRouter dispatch lands in v0.2."
        )

    def pricing(self, model: str) -> tuple[float, float]:
        # OpenRouter exposes per-model pricing via API; placeholder until live.
        return (2.0, 8.0)
