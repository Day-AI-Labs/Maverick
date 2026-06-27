"""AWS Bedrock provider (OpenAI-compatible endpoint).

Bedrock now exposes an OpenAI-compatible chat-completions endpoint per
region, so we reuse OpenAIClient rather than hand-rolling the SigV4 +
InvokeModel path. Users who need the native boto3 ``bedrock-runtime``
path can still set up a custom provider; this covers the common case.

Env:
  - AWS_REGION (required; e.g. us-east-1)
  - BEDROCK_API_KEY (Bedrock API key — the short-lived bearer Amazon
    issues for the OpenAI-compatible endpoint)
  - BEDROCK_MODEL_ID (default anthropic.claude-sonnet-4-20250514-v1:0)

The base URL is
  https://bedrock-runtime.<region>.amazonaws.com/openai/v1
"""
from __future__ import annotations

import os

from .openai_provider import OpenAIClient


class BedrockClient(OpenAIClient):
    DEFAULT_MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        region = os.environ.get("AWS_REGION", "").strip()
        if not region:
            raise RuntimeError("Bedrock requires AWS_REGION (e.g. us-east-1).")
        key = api_key or os.environ.get("BEDROCK_API_KEY")
        if not key:
            # Fail fast rather than sending a fake "bedrock-no-auth" bearer that
            # the endpoint rejects with an opaque error.
            raise RuntimeError(
                "Bedrock requires BEDROCK_API_KEY (the bearer for the Bedrock "
                "OpenAI-compatible endpoint)."
            )
        url = (
            base_url
            or f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1"
        )
        super().__init__(api_key=key, base_url=url, allow_openai_env_fallback=False)
        model = os.environ.get("BEDROCK_MODEL_ID", "").strip()
        if model:
            self.DEFAULT_MODEL = model
