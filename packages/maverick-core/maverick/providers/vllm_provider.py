"""vLLM provider.

vLLM is the dominant self-hosted inference server for serving Llama,
Mixtral, Qwen, DeepSeek etc. on consumer/server GPUs. It exposes an
OpenAI-compatible ``/v1/chat/completions`` endpoint, so we re-use
the OpenAIClient base — same pattern as the TGI provider.

Why ship this alongside TGI?
  - vLLM has wider model support out of the box (TGI lags on new
    architectures by 1-3 weeks).
  - vLLM supports speculative decoding + chunked prefill, which are
    relevant performance levers users may want to dial themselves.
  - Distinct env vars + base URL default make it easier for users to
    point both servers at the same router without env collision.

Env: ``VLLM_BASE_URL`` (e.g. ``http://localhost:8000``), optional
``VLLM_API_KEY`` for deployments behind a proxy.

Default model id is ``"vllm"`` — vLLM ignores the ``model`` param
when serving a single model, but the user should still override via
``[models]`` for clarity in logs / cost reports.
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class VLLMClient(OpenAIClient):
    DEFAULT_MODEL = "vllm"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("VLLM_API_KEY") or "vllm-no-auth"
        url = (
            base_url
            or os.environ.get("VLLM_BASE_URL")
            or "http://localhost:8000/v1"
        )
        if not url.rstrip("/").endswith("/v1"):
            url = url.rstrip("/") + "/v1"
        super().__init__(api_key=key, base_url=url)
