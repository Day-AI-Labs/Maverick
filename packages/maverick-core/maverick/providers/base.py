"""Provider interface. Every LLM provider implements this contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ProviderResponse:
    text: str
    thinking: Optional[str]
    tool_calls: list[Any]
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    raw: Any = None


class Provider(ABC):
    """Abstract LLM provider.

    Implementations must support:
      - sync ``complete()`` and async ``complete_async()``
      - prompt caching where the underlying API supports it
      - tool-use schemas in a provider-native format
      - a ``pricing`` table for budget accounting
    """

    name: str  # registered in PROVIDERS

    @abstractmethod
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None): ...

    @abstractmethod
    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> ProviderResponse: ...

    @abstractmethod
    def pricing(self, model: str) -> tuple[float, float]:
        """Return ($/Mtok input, $/Mtok output) for budget tracking."""
        ...
