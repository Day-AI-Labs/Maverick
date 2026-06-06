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

import os
from dataclasses import dataclass
from typing import Any

from .budget import Budget

# Latest Claude family as of 2026-05.
MODEL_OPUS = "claude-opus-4-8"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"

# Opus 4.8 "fast mode": identical capability, ~2.5x faster output, billed
# at 2x the standard Opus rate ($10/$50). Exposed as a distinct model id so
# callers opt in explicitly; standard Opus stays the default so we never
# silently double a user's bill.
MODEL_OPUS_FAST = "claude-opus-4-8-fast"

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
    MODEL_OPUS:                  (5.0, 25.0),    # opus 4.8 (also 4.5/4.6/4.7 — same $5/$25)
    MODEL_OPUS_FAST:             (10.0, 50.0),   # opus 4.8 fast mode: 2.5x faster, 2x price
    "claude-opus-4-7":           (5.0, 25.0),    # prior Opus, still selectable in config
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
    # Google (Gemini 3.5 Flash GA at I/O 2026-05-19; 3.5 Pro followed in June)
    "gemini-3.5-pro":            (2.50, 10.0),
    "gemini-3.5-flash":          (0.15, 0.60),
    "gemini-3-pro":              (2.50, 10.0),
    "gemini-3-flash":            (0.15, 0.60),
    # OpenRouter vendor/model ids (cheap, near-frontier-on-coding open models).
    # Keyed by the OpenRouter `vendor/model` id because that is the bare
    # model_id _lookup_price sees after stripping the `openrouter:` prefix.
    # TODO: verify each rate against https://openrouter.ai pricing before relying
    # on these for billing — placeholders below are best-effort May/June 2026.
    "minimax/minimax-m2.5":      (0.30, 1.20),    # MiniMax M2.5 — verify on openrouter.ai
    "deepseek/deepseek-v4-pro":  (0.14, 0.55),    # DeepSeek V4 Pro via OpenRouter — verify
    "qwen/qwen3-coder-next":     (0.20, 0.80),    # Qwen3 Coder Next via OpenRouter — verify
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
    thinking: str | None
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
    thinking_blocks: list[tuple[str, str | None]] = None  # type: ignore
    # Legacy field kept for back-compat with mocks; equals
    # thinking_blocks[0][1] if thinking_blocks present.
    thinking_signature: str | None = None
    # May 28 fix: the model's output blocks in their ORIGINAL order,
    # already in Anthropic content-block dict form (thinking /
    # redacted_thinking / text / tool_use, interleaved as returned).
    # Anthropic forbids rearranging the thinking-block sequence
    # relative to tool_use ("you can't rearrange or modify the
    # sequence of these blocks"), so the bucketed thinking/text/
    # tool_calls fields above cannot rebuild an interleaved Opus 4.7
    # turn faithfully. agent.py replays these verbatim when present;
    # None for providers that don't emit interleaved thinking (they
    # fall back to the bucketed reconstruction).
    content_blocks: list[dict] | None = None

    def __post_init__(self):
        if self.thinking_blocks is None:
            # Back-compat: synthesize from the legacy single fields.
            if self.thinking:
                self.thinking_blocks = [(self.thinking, self.thinking_signature)]
            else:
                self.thinking_blocks = []


def model_for_role(role: str) -> str:
    """Return the model spec for a role (may be 'provider:id' or bare id).

    Resolution order:
      1. Per-role env override `MAVERICK_MODEL_OVERRIDE_<ROLE>` (set by
         best-of-N to swap models per attempt).
      2. Global override `MAVERICK_MODEL_OVERRIDE` (set by the CLI's
         `maverick --model <id>` flag) -- an explicit, run-wide choice that
         beats config so the documented flag actually applies to every agent.
      3. ``~/.maverick/config.toml`` -> ``[models]`` -> role
      4. Cost-aware router (opt-in: `MAVERICK_COST_ROUTING=1` or
         `[routing] cost_aware = true`) -- among the user's configured
         providers, the cheapest one at the role's capability tier.
      5. ``ROLE_MODELS`` defaults
      6. ``DEFAULT_MODEL``

    The user's explicit choices (1, 2, 3) always win; the router only gets a
    say when no model was pinned, and it returns None (defers to 5) unless
    the operator opted in. This keeps "users own model choice" intact.
    """
    import os
    override = os.environ.get(f"MAVERICK_MODEL_OVERRIDE_{role.upper()}")
    if override:
        return override
    # Global CLI override (`maverick --model <id>`): an explicit run-wide
    # choice. Beats config so the flag isn't silently ignored by per-role
    # config/defaults (which it was, before this).
    global_override = os.environ.get("MAVERICK_MODEL_OVERRIDE")
    if global_override:
        return global_override
    try:
        from .config import get_role_model
        spec = get_role_model(role)
        if spec:
            return spec
    except Exception:
        pass
    # Cost-aware routing (opt-in, off by default). pick() returns None when
    # disabled or when no provider is configured, so this is a no-op for the
    # default install.
    try:
        from .cost_router import pick, signal_for_role
        routed = pick(signal_for_role(role))
        if routed:
            return routed
    except Exception:  # pragma: no cover -- never let routing break resolution
        pass
    return ROLE_MODELS.get(role, DEFAULT_MODEL)


def _parse_spec(spec: str) -> tuple[str, str]:
    """Parse ``provider:model-id`` or bare ``model-id`` (= anthropic).

    The provider half is canonicalized (lowercased, alias-resolved via the
    provider registry) so a user-typed ``Anthropic:`` or an advertised alias
    like ``claude:`` resolves the same as ``anthropic:`` -- not just for client
    creation (which already canonicalizes) but for the case-sensitive API-key
    lookup in ``_provider_api_key``, which would otherwise miss the key and
    fail auth at call time.
    """
    if ":" in spec:
        provider, model_id = spec.split(":", 1)
    else:
        provider, model_id = "anthropic", spec
    from .providers import _canonical
    return _canonical(provider), model_id


def _configured_provider_api_key(provider: str) -> str | None:
    """Return a provider api_key from config, normalized for client use."""
    from .config import get_provider_config

    try:
        key = (get_provider_config(provider) or {}).get("api_key")
    except Exception:
        return None
    if isinstance(key, str):
        return key.strip() or None
    return str(key).strip() if key else None


def _provider_api_key(provider: str, anthropic_api_key: str | None) -> str | None:
    """Return the explicit API key override for provider-client creation."""
    if provider == "anthropic" and anthropic_api_key:
        return anthropic_api_key
    key = _configured_provider_api_key(provider)
    if key:
        return key
    env_keys = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "moonshot": ("MOONSHOT_API_KEY",),
        "xai": ("XAI_API_KEY", "GROK_API_KEY"),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "openrouter": ("OPENROUTER_API_KEY",),
    }
    for env_key in env_keys.get(provider, ()):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return None


def _run_preflight(model_id, system, messages, tools, max_tokens) -> None:
    """Token preflight before an LLM dispatch (roadmap 'token preflight v1').

    Mode via the ``MAVERICK_PREFLIGHT`` env var:
      - ``warn`` (default): log a warning if the estimated request won't fit
        the model's context, but still dispatch;
      - ``strict``: raise ``PreflightFailed`` so the caller can hard-refuse
        before burning tokens on a doomed call;
      - ``off``: skip entirely.

    Default is ``warn`` so wiring preflight onto the live path can't turn a
    borderline-but-valid request into a false refusal (the estimate is a
    cheap chars/token heuristic); operators opt into hard-refuse explicitly.
    """
    mode = os.environ.get("MAVERICK_PREFLIGHT", "warn").strip().lower()
    if mode not in ("warn", "strict"):
        return  # 'off' / unrecognized -> skip
    try:
        from .preflight import preflight
    except ImportError:  # pragma: no cover
        return
    # strict=True makes preflight() raise PreflightFailed (propagates to the
    # caller); warn mode only logs.
    preflight(
        model=model_id, system=system, messages=messages,
        tools=tools, max_tokens=max_tokens, strict=(mode == "strict"),
    )


def _estimate_call_cost(model_id, system, messages, tools, max_tokens) -> float:
    """Rough $ for one call BEFORE dispatch: estimated input tokens at the
    model's input rate + max_tokens at the output rate (chars/4 heuristic,
    matching the token preflight). Input dominates -- a 200k-token context is
    the cost driver -- so output using the full max_tokens is acceptably
    conservative."""
    from .budget import _lookup_price
    in_rate, out_rate = _lookup_price(model_id)
    chars = len(system or "")
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else m
        chars += len(c) if isinstance(c, str) else len(str(c))
    for t in tools or []:
        chars += len(str(t))
    return (chars / 4 / 1_000_000) * in_rate + (max_tokens / 1_000_000) * out_rate


class LLM:
    """Multi-provider LLM dispatcher.

    Holds a cache of provider-specific client instances. Each call routes
    to the right one based on the model spec (defaults to ``self.model``).

    Drop-in replacement for the previous anthropic-only LLM class.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
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
                from .providers import KNOWN_PROVIDERS, get_provider_client
                from .session_providers import is_session_provider
                key = _provider_api_key(provider, self._anthropic_api_key)
                use_api_provider = (
                    provider in KNOWN_PROVIDERS
                    and (not is_session_provider(provider) or key)
                )
                if use_api_provider or key:
                    self._clients[provider] = get_provider_client(provider, api_key=key)
                else:
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
                        self._clients[provider] = get_provider_client(provider, api_key=key)
            return self._clients[provider]

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
        on_delta=None,
    ) -> LLMResponse:
        provider, model_id = _parse_spec(model or self.model)
        _run_preflight(model_id, system, messages, tools, max_tokens)
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
            from .observability import (
                gen_ai_attributes as _gen_ai_attributes,
            )
            from .observability import (
                gen_ai_span_name as _gen_ai_span_name,
            )
            from .observability import (
                trace_span as _trace_span,
            )
        except ImportError:  # pragma: no cover
            import contextlib
            def _trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()
            def _gen_ai_span_name(op, model):  # type: ignore
                return f"{op} {model}"
            def _gen_ai_attributes(*a, **kw):  # type: ignore
                return {}
        _t0 = _time.time()
        _d0 = budget.dollars if budget else 0.0
        _err = False
        try:
            with _trace_span(
                _gen_ai_span_name("chat", model_id),
                attributes={
                    "llm.provider": provider, "llm.model": model_id,
                    **_gen_ai_attributes(provider, model_id),
                },
            ):
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
                    # inc() by THIS call's delta, not the per-goal cumulative
                    # total: budget_dollars is a lifetime counter, and passing
                    # the per-goal accumulator let a fresh goal stomp it.
                    _rm("budget_dollars", _spent)
            except Exception:  # pragma: no cover
                pass

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        provider, model_id = _parse_spec(model or self.model)
        _run_preflight(model_id, system, messages, tools, max_tokens)
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
            from .observability import (
                gen_ai_attributes as _gen_ai_attributes,
            )
            from .observability import (
                gen_ai_span_name as _gen_ai_span_name,
            )
            from .observability import (
                trace_span as _trace_span,
            )
        except ImportError:  # pragma: no cover
            import contextlib
            def _trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()
            def _gen_ai_span_name(op, model):  # type: ignore
                return f"{op} {model}"
            def _gen_ai_attributes(*a, **kw):  # type: ignore
                return {}
        _t0 = _time.time()
        _d0 = budget.dollars if budget else 0.0
        _err = False
        # Hold this call's projected cost against the cap BEFORE dispatching, so
        # concurrent sub-agents on a shared budget can't each pass an individual
        # check and then collectively overshoot (a $2.50 cap reached $6+ with a
        # wide parallel fan-out). reserve() raises BudgetExceeded here if the
        # call won't fit; released in `finally` once the actual spend lands.
        _held = budget.reserve(
            _estimate_call_cost(model_id, system, messages, tools, max_tokens)
        ) if budget is not None else 0.0
        try:
            with _trace_span(
                _gen_ai_span_name("chat", model_id),
                attributes={
                    "llm.provider": provider, "llm.model": model_id,
                    **_gen_ai_attributes(provider, model_id),
                },
            ):
                return await client.complete_async(
                    system=system, messages=messages, tools=tools, budget=budget,
                    max_tokens=max_tokens, thinking_budget=thinking_budget, model=model_id,
                )
        except Exception:
            _err = True
            raise
        finally:
            if _held:
                budget.release(_held)
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
                    # inc() by THIS call's delta, not the per-goal cumulative
                    # total: budget_dollars is a lifetime counter, and passing
                    # the per-goal accumulator let a fresh goal stomp it.
                    _rm("budget_dollars", _spent)
            except Exception:  # pragma: no cover
                pass
