"""Generic OpenAI-compatible provider (base_url-driven).

Many inference servers and gateways speak the OpenAI chat-completions
protocol but live at an arbitrary base_url: LM Studio, llama.cpp's
server, Together, Groq, and any private OpenAI-compatible proxy. Rather
than ship a bespoke client per vendor, this provider re-uses the
OpenAIClient base and reads ``base_url`` + ``api_key`` from
``[providers.openai_compatible]`` in config (or env).

Config::

    [providers.openai_compatible]
    base_url = "https://api.groq.com/openai/v1"
    api_key  = "${GROQ_API_KEY}"

Env fallback: ``OPENAI_COMPATIBLE_BASE_URL`` / ``OPENAI_COMPATIBLE_API_KEY``.

The base_url is passed through verbatim — supply the full documented
endpoint (e.g. Groq's ``/openai/v1``); we don't rewrite it. Model id is
user-chosen via ``[models]``; the placeholder DEFAULT_MODEL is only a
last-resort label.
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class OpenAICompatibleClient(OpenAIClient):
    DEFAULT_MODEL = "openai-compatible"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        from ..config import get_provider_config

        cfg = get_provider_config("openai_compatible")
        url = (
            base_url
            or cfg.get("base_url")
            or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
        )
        if not url:
            raise ValueError(
                "openai-compatible provider needs a base_url. Set "
                "[providers.openai_compatible] base_url in config.toml or "
                "the OPENAI_COMPATIBLE_BASE_URL env var (e.g. a LM Studio / "
                "llama.cpp / Together / Groq endpoint)."
            )
        key = (
            api_key
            or cfg.get("api_key")
            or os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        )
        super().__init__(
            api_key=key,
            base_url=url,
            allow_openai_env_fallback=False,
        )
