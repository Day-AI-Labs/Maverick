"""HuggingFace Text Generation Inference (TGI) provider.

TGI is HuggingFace's open-source inference server for self-hosted
LLMs (Llama, Mistral, Qwen, etc.). It exposes an OpenAI-compatible
``/v1/chat/completions`` endpoint when launched with `--openai`, so we
can re-use the OpenAIClient base.

Env: TGI_BASE_URL (e.g. http://localhost:8080), optional TGI_API_KEY
for deployments behind a proxy.

Default model id is "tgi" (a placeholder — TGI ignores the model
param since it serves one model per process). Users override via
config.toml [models].
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class TGIClient(OpenAIClient):
    DEFAULT_MODEL = "tgi"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("TGI_API_KEY") or "tgi-no-auth"
        url = (
            base_url
            or os.environ.get("TGI_BASE_URL")
            or "http://localhost:8080/v1"
        )
        # Normalize: accept both `http://host:8080` and
        # `http://host:8080/v1`.
        if not url.rstrip("/").endswith("/v1"):
            url = url.rstrip("/") + "/v1"
        super().__init__(api_key=key, base_url=url)
