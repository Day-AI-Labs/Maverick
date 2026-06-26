"""Ollama provider client.

Local models via Ollama's OpenAI-compatible API at ``/v1``. Nothing
leaves the user's machine; pricing is implicitly $0 since inference
runs locally.

Default base_url is ``http://localhost:11434/v1``. Override via
``[providers.ollama] base_url`` in config.
"""
from __future__ import annotations

from .openai_provider import OpenAIClient


class OllamaClient(OpenAIClient):
    DEFAULT_MODEL = "llama3.3:70b"
    PRICE_MODEL_PREFIX = "ollama:"  # self-hosted: unknown ids price $0
    USAGE_REQUIRED = False  # local server may omit usage; $0 -> nothing to enforce

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        super().__init__(
            api_key=api_key or "ollama",  # placeholder; Ollama ignores it
            base_url=base_url or "http://localhost:11434/v1",
        )
