"""Provider abstraction for multi-LLM routing.

v0.1: only ``AnthropicProvider`` is fully wired up in the agent loop
(via ``maverick.llm``). Other providers exist as stubs — the installer
wizard can offer them, config files can reference them, but the agent
falls back to a clear error if the user tries to actually route a role
to a stub.

A future commit refactors ``maverick.llm.LLM`` to dispatch through the
provider registry based on the ``provider:model-id`` spec from config.
For now, ``llm.model_for_role`` strips the provider prefix and the
Anthropic adapter is used unconditionally.
"""
from .base import Provider, ProviderResponse
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider
from .openrouter_provider import OpenRouterProvider
from .ollama_provider import OllamaProvider

PROVIDERS: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
}


def get_provider(name: str) -> type[Provider]:
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}. Available: {list(PROVIDERS)}")
    return PROVIDERS[name]


__all__ = [
    "Provider",
    "ProviderResponse",
    "AnthropicProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "PROVIDERS",
    "get_provider",
]
