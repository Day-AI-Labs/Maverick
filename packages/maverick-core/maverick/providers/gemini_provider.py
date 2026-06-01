"""Gemini provider client.

Google's Gemini exposes an OpenAI-compatible endpoint at
``https://generativelanguage.googleapis.com/v1beta/openai/``, so we can
reuse OpenAIClient with just a different base_url + API key.

Set ``GEMINI_API_KEY`` (preferred) or ``GOOGLE_API_KEY``.
"""
from __future__ import annotations

import os

from .openai_provider import OpenAIClient


class GeminiClient(OpenAIClient):
    # Match the maintained MODEL_PRICES (gemini-3.5-*). The stale 2.5-pro
    # default was absent from MODEL_PRICES, so billing fell through to the
    # cost_router's 2.5 row and charged ~2x the real Gemini 3.5 rate.
    DEFAULT_MODEL = "gemini-3.5-pro"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        super().__init__(
            api_key=key,
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
            # Don't silently fall back to OPENAI_API_KEY when no Gemini key is
            # set -- that would send the OpenAI key to Google's endpoint.
            allow_openai_env_fallback=False,
        )
