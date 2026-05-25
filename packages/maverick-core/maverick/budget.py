"""Budget tracking. Long-horizon agents need hard caps.

v0.2 cost-correctness fix:
  - record_tokens() takes the actual model id (default falls back to
    Sonnet rate for back-compat). Before this, an Opus orchestrator
    call was billed at Sonnet rate, so max_dollars=5 was letting
    ~$25 of real spend through.
  - Cache tokens are priced correctly. Anthropic charges 0.1x for
    cache reads and 1.25x for cache writes. The provider used to
    collapse everything into ``input_tokens`` at full price.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


class BudgetExceeded(Exception):
    pass


# Fallback price (Sonnet 4.6 list, no cache discount) in $/Mtok.
# Used only when the model id isn't in maverick.llm.MODEL_PRICES.
_FALLBACK_PRICE_IN = 3.0
_FALLBACK_PRICE_OUT = 15.0

# Anthropic cache multipliers (over the list input price).
_CACHE_READ_MULT = 0.1     # 90% discount on cache reads
_CACHE_WRITE_MULT = 1.25   # 25% premium on cache writes


def _lookup_price(model: Optional[str]) -> tuple[float, float]:
    """Return (in_per_mtok, out_per_mtok) for a model id. Falls back to Sonnet."""
    if not model:
        return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT
    try:
        from .llm import MODEL_PRICES
    except ImportError:
        return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    # Try prefix match (e.g. "anthropic:claude-opus-4-7" -> "claude-opus-4-7")
    if ":" in model:
        bare = model.split(":", 1)[1]
        if bare in MODEL_PRICES:
            return MODEL_PRICES[bare]
    return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT


@dataclass
class Budget:
    max_input_tokens: int = 1_000_000
    max_output_tokens: int = 200_000
    max_dollars: float = 5.0
    max_wall_seconds: float = 3600.0
    max_tool_calls: int = 500

    input_tokens: int = 0
    output_tokens: int = 0
    dollars: float = 0.0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.time)

    # Legacy defaults; only used when ``model`` isn't passed.
    price_in_per_mtok: float = _FALLBACK_PRICE_IN
    price_out_per_mtok: float = _FALLBACK_PRICE_OUT

    def record_tokens(
        self,
        in_tok: int,
        out_tok: int,
        *,
        model: Optional[str] = None,
        cache_read_tok: int = 0,
        cache_write_tok: int = 0,
    ) -> None:
        """Add usage from one LLM call.

        ``in_tok`` is the number of input tokens billed at full rate
        (i.e. excludes the cache_read_tok and cache_write_tok counts).
        ``cache_read_tok`` is billed at 0.1x, ``cache_write_tok`` at 1.25x.
        """
        self.input_tokens += in_tok + cache_read_tok + cache_write_tok
        self.output_tokens += out_tok

        in_rate, out_rate = _lookup_price(model)
        self.dollars += (in_tok / 1_000_000) * in_rate
        self.dollars += (cache_read_tok / 1_000_000) * in_rate * _CACHE_READ_MULT
        self.dollars += (cache_write_tok / 1_000_000) * in_rate * _CACHE_WRITE_MULT
        self.dollars += (out_tok / 1_000_000) * out_rate
        self.check()

    def record_tool_call(self) -> None:
        self.tool_calls += 1
        self.check()

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def check(self) -> None:
        if self.input_tokens > self.max_input_tokens:
            raise BudgetExceeded(f"input tokens {self.input_tokens} > {self.max_input_tokens}")
        if self.output_tokens > self.max_output_tokens:
            raise BudgetExceeded(f"output tokens {self.output_tokens} > {self.max_output_tokens}")
        if self.dollars > self.max_dollars:
            raise BudgetExceeded(f"${self.dollars:.2f} > ${self.max_dollars:.2f}")
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool calls {self.tool_calls} > {self.max_tool_calls}")
        if self.elapsed() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall time {self.elapsed():.0f}s > {self.max_wall_seconds:.0f}s")

    def summary(self) -> str:
        return (
            f"tokens in={self.input_tokens} out={self.output_tokens} "
            f"$={self.dollars:.3f} tools={self.tool_calls} wall={self.elapsed():.0f}s"
        )
