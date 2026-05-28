"""Provider registry. Multi-provider LLM dispatch.

Each provider client implements the same interface as ``AnthropicClient``:

    complete(system, messages, tools=None, budget=None, ...) -> LLMResponse
    complete_async(system, messages, tools=None, budget=None, ...) -> LLMResponse

Accepting Anthropic-format messages/tools and returning a
``maverick.llm.LLMResponse``. OpenAI/OpenRouter/Ollama/Gemini/Moonshot/
DeepSeek/xAI clients translate the format on the fly.
"""
from __future__ import annotations

from typing import Any, Optional


# Each entry: (canonical name, list of accepted aliases).
# Aliases let users type the brand name they know (kimi → moonshot,
# grok → xai) without us redefining the canonical provider id.
_PROVIDER_ALIASES = {
    "anthropic":  ("claude",),
    "openai":     ("chatgpt", "gpt"),
    "moonshot":   ("kimi",),
    "xai":        ("grok",),
    "gemini":     ("google",),
    "deepseek":   (),
    "openrouter": (),
    "ollama":     ("local",),
    "tgi":        ("huggingface-tgi", "hf-tgi"),
    "vllm":       (),
}


def _canonical(name: str) -> str:
    """Map an alias to the canonical provider name."""
    lower = (name or "").strip().lower()
    if lower in _PROVIDER_ALIASES:
        return lower
    for canon, aliases in _PROVIDER_ALIASES.items():
        if lower in aliases:
            return canon
    return lower


def get_provider_client(name: str, api_key: Optional[str] = None) -> Any:
    """Lazy-import and instantiate the named provider client."""
    canon = _canonical(name)
    if canon == "anthropic":
        from .anthropic_provider import AnthropicClient
        return AnthropicClient(api_key=api_key)
    if canon == "openai":
        from .openai_provider import OpenAIClient
        return OpenAIClient(api_key=api_key)
    if canon == "openrouter":
        from .openrouter_provider import OpenRouterClient
        return OpenRouterClient(api_key=api_key)
    if canon == "ollama":
        from .ollama_provider import OllamaClient
        return OllamaClient()
    if canon == "gemini":
        from .gemini_provider import GeminiClient
        return GeminiClient(api_key=api_key)
    if canon == "moonshot":
        from .moonshot_provider import MoonshotClient
        return MoonshotClient(api_key=api_key)
    if canon == "deepseek":
        from .deepseek_provider import DeepSeekClient
        return DeepSeekClient(api_key=api_key)
    if canon == "xai":
        from .xai_provider import XaiClient
        return XaiClient(api_key=api_key)
    if canon == "tgi":
        from .tgi_provider import TGIClient
        return TGIClient(api_key=api_key)
    if canon == "vllm":
        from .vllm_provider import VLLMClient
        return VLLMClient(api_key=api_key)
    raise ValueError(
        f"unknown provider {name!r}. Available: "
        + ", ".join(KNOWN_PROVIDERS)
    )


KNOWN_PROVIDERS = (
    "anthropic", "openai", "moonshot", "xai", "gemini",
    "deepseek", "openrouter", "ollama", "tgi", "vllm",
)


__all__ = ["get_provider_client", "KNOWN_PROVIDERS"]
