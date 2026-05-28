"""Multi-provider LLM facade.

Dispatches to provider-specific clients based on the ``provider:model-id``
spec. Bare model ids (no colon) default to anthropic for backward
compatibility with the original kernel.

Provider clients (in ``maverick.providers``):
  - anthropic   (claude-*) full impl with caching/thinking/streaming
  - openai      (gpt-*, o1) OpenAI Chat Completions, translates Anthropic format
  - openrouter  (any/model) OpenAI-compatible via openrouter.ai
  - ollama      (llama*, qwen*, phi*, ...) OpenAI-compatible via localhost:11434

The agent kernel only sees the ``LLM`` class; it doesn't know or care
which provider runs a given call. A run can route the orchestrator to
Anthropic Opus, workers to local Ollama, and the summarizer to OpenAI
gpt-4o-mini — all in the same swarm.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .budget import Budget


# Latest Claude family as of 2026-05.
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"

DEFAULT_MODEL = MODEL_SONNET


# Per-role default model picks (bare = anthropic). Users override via config.toml.
ROLE_MODELS: dict[str, str] = {
    "orchestrator":    MODEL_OPUS,
    "researcher":      MODEL_SONNET,
    "coder":           MODEL_SONNET,
    "writer":          MODEL_SONNET,
    "analyst":         MODEL_SONNET,
    "revisor":         MODEL_OPUS,
    "verifier":        MODEL_SONNET,
    "summarizer":      MODEL_HAIKU,
    "skill_distiller": MODEL_SONNET,
}


# Per-million-token list prices (May 2026, no cache discount, USD).
# Used by Budget.record_tokens to compute spend accurately per model.
#
# Wave 12 hotfix: an earlier Wave 12 commit raised Opus to ($15, $75)
# based on a confused reading of Anthropic's docs (those are the
# legacy Opus 4.0/4.1 rates; Opus 4.5/4.6/4.7 are all priced at
# $5/$25). Verified May 2026 against
# https://platform.claude.com/docs/en/about-claude/pricing and against
# vals.ai's measured Opus 4.7 cost-per-test of $2.42 (which only
# reconciles with $5/$25). Reverting to the correct ($5.0, $25.0).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # Anthropic (verified May 2026 against platform.claude.com/docs/.../pricing)
    MODEL_OPUS:                  (5.0, 25.0),    # opus 4.7 (also 4.5, 4.6)
    MODEL_SONNET:                (3.0, 15.0),    # sonnet 4.6
    MODEL_HAIKU:                 (1.0, 5.0),     # haiku 4.5
    # OpenAI (only enable after verifying against platform.openai.com/docs/pricing
    # for your specific model ids; the prior values were speculative SKUs).
    "gpt-5.5":                   (5.0, 20.0),
    "gpt-5.4":                   (3.0, 12.0),
    "gpt-5.4-pro":               (10.0, 40.0),
    "gpt-5.4-mini":              (0.50, 2.0),
    "gpt-5.4-nano":              (0.10, 0.40),
    # OpenRouter / DeepSeek (May 26 update: actual DeepSeek API pricing,
    # not OpenRouter aliases. https://platform.deepseek.com/api-docs/pricing)
    "deepseek-chat":             (0.27, 1.10),    # V3.2 — cache off
    "deepseek-reasoner":         (0.55, 2.19),    # R1-line
    "deepseek-v4-pro":           (0.14, 0.55),
    "deepseek-v4-flash":         (0.07, 0.28),
    # xAI Grok (May 26: https://docs.x.ai/docs/models#models-and-pricing)
    "grok-4-latest":             (3.00, 15.00),
    "grok-4-mini":               (0.30, 0.50),
    "grok-code-fast":            (0.20, 1.50),
    "grok-3":                    (3.00, 15.00),
    "grok-4.3":                  (1.25, 2.50),
    # Moonshot / Kimi (May 26: https://platform.moonshot.ai/pricing)
    "kimi-k2":                   (0.60, 2.50),
    "kimi-k1.5":                 (0.20, 2.00),
    "moonshot-v1-8k":            (0.30, 0.30),
    "moonshot-v1-32k":           (0.60, 0.60),
    "moonshot-v1-128k":          (1.20, 1.20),
    # Google
    "gemini-3-pro":              (2.50, 10.0),
    "gemini-3-flash":            (0.15, 0.60),
    # Open-weight defaults via Ollama: priced at zero (compute cost).
    "qwen3-coder-next":          (0.0, 0.0),
    "qwen3-32b":                 (0.0, 0.0),
    "llama-4-maverick":          (0.0, 0.0),
}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    thinking: Optional[str]
    tool_calls: list[ToolCall]
    stop_reason: str
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    raw: Any = None
    # May 26 smoke fix: thinking-block signatures.
    # Anthropic emits one signature per thinking block; when those
    # blocks come back as assistant history, EACH must carry its
    # own original signature. The earlier single-string field
    # `thinking_signature` worked for single-block adaptive runs
    # but corrupts multi-block interleaved thinking (Opus 4.7).
    # Now: store the original (text, signature) pairs so agent.py
    # can reconstruct multiple thinking blocks faithfully.
    thinking_blocks: list[tuple[str, Optional[str]]] = None  # type: ignore
    # Legacy field kept for back-compat with mocks; equals
    # thinking_blocks[0][1] if thinking_blocks present.
    thinking_signature: Optional[str] = None

    def __post_init__(self):
        if self.thinking_blocks is None:
            # Back-compat: synthesize from the legacy single fields.
            if self.thinking:
                self.thinking_blocks = [(self.thinking, self.thinking_signature)]
            else:
                self.thinking_blocks = []


def model_for_role(role: str) -> str:
    """Return the model spec for a role (may be 'provider:id' or bare id).

    Resolution order (Wave 11):
      1. Per-role env override `MAVERICK_MODEL_OVERRIDE_<ROLE>` (set by
         best-of-N to swap models per attempt).
      2. ``~/.maverick/config.toml`` -> ``[models]`` -> role
      3. ``ROLE_MODELS`` defaults
      4. ``DEFAULT_MODEL``
    """
    import os
    override = os.environ.get(f"MAVERICK_MODEL_OVERRIDE_{role.upper()}")
    if override:
        return override
    try:
        from .config import get_role_model
        spec = get_role_model(role)
        if spec:
            return spec
    except Exception:
        pass
    return ROLE_MODELS.get(role, DEFAULT_MODEL)


def _parse_spec(spec: str) -> tuple[str, str]:
    """Parse ``provider:model-id`` or bare ``model-id`` (= anthropic)."""
    if ":" in spec:
        provider, model_id = spec.split(":", 1)
        return provider, model_id
    return "anthropic", spec


class LLM:
    """Multi-provider LLM dispatcher.

    Holds a cache of provider-specific client instances. Each call routes
    to the right one based on the model spec (defaults to ``self.model``).

    Drop-in replacement for the previous anthropic-only LLM class.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None):
        self.model = model
        self._anthropic_api_key = api_key  # legacy back-compat
        self._clients: dict[str, Any] = {}
        # Wave 12 (council F12a): lock the provider cache so two
        # concurrent calls don't double-init httpx connection pools.
        import threading as _threading
        self._clients_lock = _threading.Lock()

    def _get_client(self, provider: str):
        # Fast-path: read without lock (dict reads are atomic in CPython).
        if provider in self._clients:
            return self._clients[provider]
        with self._clients_lock:
            # Re-check under the lock in case another thread populated it.
            if provider not in self._clients:
                from .session_providers import is_session_provider
                if is_session_provider(provider):
                    # Session providers get auto-wrapped in the tool
                    # simulator so tool-using roles (orchestrator,
                    # coder, researcher) work transparently. The
                    # wrapper is a no-op when tools=None.
                    from .session_providers import get_session_client
                    self._clients[provider] = get_session_client(
                        provider, simulate_tools=True,
                    )
                else:
                    from .providers import get_provider_client
                    key = self._anthropic_api_key if provider == "anthropic" else None
                    self._clients[provider] = get_provider_client(provider, api_key=key)
            return self._clients[provider]

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
        on_delta=None,
    ) -> LLMResponse:
        provider, model_id = _parse_spec(model or self.model)
        client = self._get_client(provider)
        kwargs: dict[str, Any] = dict(
            system=system, messages=messages, tools=tools, budget=budget,
            max_tokens=max_tokens, thinking_budget=thinking_budget, model=model_id,
        )
        if on_delta is not None and provider == "anthropic":
            kwargs["on_delta"] = on_delta
        import time as _time
        try:
            from .chaos import maybe_fail
            maybe_fail("llm_call", message=f"chaos: llm_call provider={provider}")
        except ImportError:
            pass
        try:
            from .observability import trace_span as _trace_span
        except ImportError:  # pragma: no cover
            import contextlib
            def _trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()
        _t0 = _time.time()
        _d0 = budget.dollars if budget else 0.0
        _err = False
        try:
            with _trace_span("llm.complete", attributes={
                "llm.provider": provider, "llm.model": model_id,
            }):
                return client.complete(**kwargs)
        except Exception:
            _err = True
            raise
        finally:
            _dt_ms = (_time.time() - _t0) * 1000.0
            _spent = (budget.dollars - _d0) if budget else 0.0
            try:
                from .provider_health import get as _h
                _h().record(provider, model_id,
                            latency_ms=_dt_ms, dollars=_spent, error=_err)
            except Exception:  # pragma: no cover -- never fail on stats
                pass
            try:
                from .observability import record_metric as _rm
                _rm("llm_calls", labels={"provider": provider, "model": model_id})
                _rm("llm_latency", _dt_ms / 1000.0,
                    labels={"provider": provider, "model": model_id})
                if budget is not None:
                    _rm("budget_dollars", budget.dollars)
            except Exception:  # pragma: no cover
                pass

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        provider, model_id = _parse_spec(model or self.model)
        client = self._get_client(provider)
        import time as _time
        # complete_async is the PRIMARY agent-loop path; the sync complete()
        # had the chaos hook + trace span but this one didn't, so chaos
        # injection and OTLP LLM spans never fired on the live path.
        try:
            from .chaos import maybe_fail
            maybe_fail("llm_call", message=f"chaos: llm_call provider={provider}")
        except ImportError:
            pass
        try:
            from .observability import trace_span as _trace_span
        except ImportError:  # pragma: no cover
            import contextlib
            def _trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()
        _t0 = _time.time()
        _d0 = budget.dollars if budget else 0.0
        _err = False
        try:
            with _trace_span("llm.complete", attributes={
                "llm.provider": provider, "llm.model": model_id,
            }):
                return await client.complete_async(
                    system=system, messages=messages, tools=tools, budget=budget,
                    max_tokens=max_tokens, thinking_budget=thinking_budget, model=model_id,
                )
        except Exception:
            _err = True
            raise
        finally:
            _dt_ms = (_time.time() - _t0) * 1000.0
            _spent = (budget.dollars - _d0) if budget else 0.0
            try:
                from .provider_health import get as _h
                _h().record(provider, model_id,
                            latency_ms=_dt_ms, dollars=_spent, error=_err)
            except Exception:  # pragma: no cover
                pass
            try:
                from .observability import record_metric as _rm
                _rm("llm_calls", labels={"provider": provider, "model": model_id})
                _rm("llm_latency", _dt_ms / 1000.0,
                    labels={"provider": provider, "model": model_id})
                if budget is not None:
                    _rm("budget_dollars", budget.dollars)
            except Exception:  # pragma: no cover
                pass
