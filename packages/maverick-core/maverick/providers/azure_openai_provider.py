"""Azure OpenAI provider.

Azure's Chat Completions API is OpenAI-compatible at the *wire* level,
but it differs from vanilla OpenAI in two ways the plain ``OpenAI``
client cannot express:

  1. auth is the ``api-key`` HTTP header, NOT ``Authorization: Bearer``
  2. an ``api-version`` query param is required on every request, and
     requests route to a *deployment* (not a model id)

The OpenAI SDK ships a dedicated ``AzureOpenAI`` / ``AsyncAzureOpenAI``
client that handles both. Passing an Azure URL with ``?api-version=``
baked into ``base_url`` to the plain ``OpenAI`` client does NOT work:
the SDK's URL join drops the query string and mangles the deployment
path segment, and it sends a Bearer header Azure ignores. So we build
the Azure clients directly here rather than reusing
``OpenAIClient.__init__``.

Env:
  - AZURE_OPENAI_ENDPOINT  (e.g. https://my-res.openai.azure.com)
  - AZURE_OPENAI_API_KEY
  - AZURE_OPENAI_DEPLOYMENT (the deployment name; used as the model)
  - AZURE_OPENAI_API_VERSION (default 2024-10-21)
"""
from __future__ import annotations

import os

from .openai_provider import OpenAIClient


class AzureOpenAIClient(OpenAIClient):
    DEFAULT_MODEL = "azure-deployment"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        try:
            from openai import AsyncAzureOpenAI, AzureOpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. Run: pip install 'maverick[openai]'"
            ) from e
        endpoint = (
            base_url
            or os.environ.get("AZURE_OPENAI_ENDPOINT")
            or ""
        ).rstrip("/")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
        if not endpoint or not deployment:
            raise RuntimeError(
                "Azure OpenAI requires AZURE_OPENAI_ENDPOINT + "
                "AZURE_OPENAI_DEPLOYMENT (+ AZURE_OPENAI_API_KEY)."
            )
        key = api_key or os.environ.get("AZURE_OPENAI_API_KEY") or "azure-no-auth"
        # Build the dedicated Azure clients directly — they send the
        # `api-key` header + `api-version` query + route to the
        # deployment. We intentionally do NOT call super().__init__:
        # it would construct a plain OpenAI client that drops the
        # api-version query and mangles the deployment path.
        self.endpoint = endpoint
        self.deployment = deployment
        self.api_version = version
        # Apply the configured HTTP timeout (the base OpenAIClient does this;
        # we bypass it here, so wire it in manually or Azure calls can hang).
        from .base import llm_http_timeout
        _timeout = llm_http_timeout()
        _extra = {"timeout": _timeout} if _timeout is not None else {}
        self._sync = AzureOpenAI(
            api_key=key,
            azure_endpoint=endpoint,
            api_version=version,
            azure_deployment=deployment,
            **_extra,
        )
        self._async = AsyncAzureOpenAI(
            api_key=key,
            azure_endpoint=endpoint,
            api_version=version,
            azure_deployment=deployment,
            **_extra,
        )
        # The deployment name is what Azure routes on; expose it as the
        # default model so the LLM facade's model id is harmless.
        self.DEFAULT_MODEL = deployment
