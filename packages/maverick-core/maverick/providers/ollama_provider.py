"""Ollama provider — stub.

Local models via Ollama's HTTP API. Planned implementation talks to
``base_url`` (default ``http://localhost:11434``) and reports ($0, $0)
for pricing since inference happens on the user's machine.

Use case: full privacy. Nothing leaves the user's machine when every
role is routed to ``ollama:*``.
"""
from __future__ import annotations

from typing import Optional

from .base import Provider, ProviderResponse


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.base_url = base_url or "http://localhost:11434"

    async def complete_async(self, system, messages, tools=None, max_tokens=4096,
                             thinking_budget=None, model=None) -> ProviderResponse:
        raise NotImplementedError(
            "OllamaProvider is not yet implemented. Use the Anthropic "
            "provider for now — local-model dispatch lands in v0.2."
        )

    def pricing(self, model: str) -> tuple[float, float]:
        return (0.0, 0.0)  # Local inference, no per-token cost.
