"""xAI (Grok) provider.

xAI's API is OpenAI-compatible at https://api.x.ai/v1.

Default model is `grok-4-latest`. Other models: `grok-4-mini`,
`grok-code-fast`, `grok-3` (legacy).

API key env var: XAI_API_KEY (or GROK_API_KEY as a common alias).
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class XaiClient(OpenAIClient):
    DEFAULT_MODEL = "grok-4-latest"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = (
            api_key
            or os.environ.get("XAI_API_KEY")
            or os.environ.get("GROK_API_KEY")
        )
        url = base_url or os.environ.get(
            "XAI_BASE_URL", "https://api.x.ai/v1",
        )
        super().__init__(
            api_key=key,
            base_url=url,
            allow_openai_env_fallback=False,
        )
