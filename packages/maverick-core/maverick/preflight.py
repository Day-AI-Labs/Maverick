"""Token-count preflight.

Before dispatching an LLM call, estimate how many input tokens it will
consume and refuse early if it exceeds the model's context (minus a
safety margin). Cheap to run; saves money + time when an agent is
about to send something that can't possibly fit.

Estimation strategy:
  - Anthropic models: rough heuristic of 3.5 chars/token, since the
    real tokenizer (BPE-derived) lives in the SDK and counting on every
    call is wasteful. Conservative bias upward by 5%.
  - OpenAI models: same heuristic. If tiktoken is installed, prefer it.
  - Other providers: 3.5 chars/token heuristic.

This is intentionally a single function, not a class hierarchy. Hot
path. Keep it dumb.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


# Hard caps per model. Conservative: subtract a safety margin so we
# leave room for the response (max_tokens param) and tools schema.
# Keys are exact model ids; lookups fall back to family prefix.
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Anthropic
    "claude-opus-4-7":    200_000,
    "claude-sonnet-4-6":  200_000,
    "claude-haiku-4-5":   200_000,
    # OpenAI
    "gpt-5.5":            128_000,
    "gpt-5.4":            128_000,
    "gpt-5.4-pro":        128_000,
    "gpt-5.4-mini":       128_000,
    "gpt-5.4-nano":        32_000,
    # xAI
    "grok-4-latest":      131_072,
    "grok-4-mini":        131_072,
    "grok-code-fast":     131_072,
    "grok-3":             131_072,
    # DeepSeek
    "deepseek-chat":       64_000,
    "deepseek-reasoner":   64_000,
    "deepseek-v4-pro":    128_000,
    "deepseek-v4-flash":  128_000,
    # Moonshot / Kimi
    "kimi-k2":            128_000,
    "kimi-k1.5":          128_000,
    "moonshot-v1-8k":       8_000,
    "moonshot-v1-32k":     32_000,
    "moonshot-v1-128k":   128_000,
    # Gemini
    "gemini-3-pro":     1_000_000,
    "gemini-3-flash":   1_000_000,
}


def context_limit(model: str) -> int:
    """Return the (conservative) context limit for ``model``.

    Falls back to family-prefix match, then 32k as the safe default
    when we have no clue.
    """
    if model in _MODEL_CONTEXT_LIMITS:
        return _MODEL_CONTEXT_LIMITS[model]
    # Family-prefix fallback.
    for prefix, limit in _MODEL_CONTEXT_LIMITS.items():
        if model.startswith(prefix.split("-")[0]):
            return limit
    return 32_000


def estimate_tokens(text: str) -> int:
    """Cheap chars/token estimator. Biases upward 5% for safety."""
    if not text:
        return 0
    return int((len(text) / 3.5) * 1.05)


def estimate_messages_tokens(
    system: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
) -> int:
    """Sum estimated tokens for a full request."""
    import json

    total = estimate_tokens(system or "")
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    txt = block.get("text") or block.get("input")
                    if isinstance(txt, str):
                        total += estimate_tokens(txt)
                    else:
                        total += estimate_tokens(json.dumps(block, default=str))
                else:
                    total += estimate_tokens(str(block))
    if tools:
        for t in tools:
            try:
                total += estimate_tokens(json.dumps(t, default=str))
            except (TypeError, ValueError):
                total += 200  # generous fallback per tool
    return total


class PreflightFailed(Exception):
    """Raised when the estimated request size won't fit the model's context."""

    def __init__(self, model: str, estimated: int, limit: int, max_tokens: int):
        msg = (
            f"preflight: model={model!r} won't fit. "
            f"estimated input tokens={estimated:,}, "
            f"context limit={limit:,}, requested output={max_tokens}. "
            "Compact, split, or pick a larger-context model."
        )
        super().__init__(msg)
        self.model = model
        self.estimated = estimated
        self.limit = limit
        self.max_tokens = max_tokens


def preflight(
    *,
    model: str,
    system: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    max_tokens: int = 4096,
    safety_margin: int = 1024,
    strict: bool = True,
) -> int:
    """Estimate input size; raise PreflightFailed if it won't fit.

    Returns the estimate (so callers can log / surface to the user).

    Set ``strict=False`` to log a warning instead of raising. The agent
    kernel uses strict mode for tool dispatch (so we never burn tokens
    on a doomed call); ad-hoc callers can be more lenient.
    """
    limit = context_limit(model)
    budget = limit - max_tokens - safety_margin
    if budget <= 0:
        # Tiny model + huge requested output: nothing's going to fit.
        raise PreflightFailed(model, 0, limit, max_tokens)
    estimated = estimate_messages_tokens(system, messages, tools)
    if estimated > budget:
        if strict:
            raise PreflightFailed(model, estimated, limit, max_tokens)
        log.warning(
            "preflight: model=%s estimated=%d > budget=%d (limit=%d, max_tokens=%d)",
            model, estimated, budget, limit, max_tokens,
        )
    return estimated


__all__ = [
    "context_limit",
    "estimate_tokens",
    "estimate_messages_tokens",
    "preflight",
    "PreflightFailed",
]
