"""OpenAI provider — stub.

Config and the wizard accept ``openai:<model>`` today but the agent
loop won't route to it until this is implemented. See
https://github.com/texasreaper62/maverick/issues for status.

The planned implementation uses the official ``openai`` SDK with the
Responses API for tool use and prompt-caching headers.
"""
from __future__ import annotations

from typing import Optional

from .base import Provider, ProviderResponse


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url

    async def complete_async(self, system, messages, tools=None, max_tokens=4096,
                             thinking_budget=None, model=None) -> ProviderResponse:
        raise NotImplementedError(
            "OpenAIProvider is not yet implemented. Switch the role to "
            "`anthropic:...` in ~/.maverick/config.toml, or watch the v0.2 "
            "milestone for OpenAI dispatch."
        )

    def pricing(self, model: str) -> tuple[float, float]:
        # Approximate 2026 list prices. Refine when implementation lands.
        table = {
            "gpt-4o":      (2.50, 10.0),
            "gpt-4o-mini": (0.15, 0.60),
            "o1":          (15.0, 60.0),
        }
        return table.get(model, (2.50, 10.0))
