"""Gemini provider client.

Google's Gemini exposes an OpenAI-compatible endpoint at
``https://generativelanguage.googleapis.com/v1beta/openai/``, so we can
reuse OpenAIClient with just a different base_url + API key.

Set ``GEMINI_API_KEY`` (preferred) or ``GOOGLE_API_KEY``.
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class GeminiClient(OpenAIClient):
    DEFAULT_MODEL = "gemini-2.5-pro"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        super().__init__(
            api_key=key,
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
            # Don't silently fall back to OPENAI_API_KEY when no Gemini key is
            # set -- that would send the OpenAI key to Google's endpoint.
            allow_openai_env_fallback=False,
        )
