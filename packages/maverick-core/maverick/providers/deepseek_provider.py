"""DeepSeek provider.

DeepSeek's API is OpenAI-compatible at https://api.deepseek.com/v1.

Default model is `deepseek-chat` (V3.2). Other models:
`deepseek-reasoner` (R1-line reasoning), `deepseek-coder`.

API key env var: DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import os

from .openai_provider import OpenAIClient


class DeepSeekClient(OpenAIClient):
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        url = base_url or os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1",
        )
        super().__init__(
            api_key=key,
            base_url=url,
            allow_openai_env_fallback=False,
        )
