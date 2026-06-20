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

from .budget import Budget, _cache_write_mult_from_ttl

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
    "vision":          MODEL_SONNET,
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
    # Older Opus tiers share the $5/$25 rate (comment above). They were absent
    # from this table, so calls fell through to the Sonnet fallback ($3/$15) --
    # a ~40% output-cost undercount, so an Opus budget overshot (user-testing
    # finding). effort.py/anthropic_provider.py still reference these ids.
    "claude-opus-4-6":           (5.0, 25.0),
    "claude-opus-4-5":           (5.0, 25.0),
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


# Curated model catalog for the dashboard's model pickers: provider -> model
# ids. The dashboard renders these as ``provider:<id>`` specs (bare for
# anthropic, the default provider) and also lets the operator type any other
# id. Admins extend the list via ``[models] catalog`` in config.toml. Prices
# live in MODEL_PRICES; a model here without a price bills at the Sonnet
# fallback until added there.
MODEL_CATALOG: dict[str, list[str]] = {
    "anthropic":  [MODEL_OPUS, MODEL_OPUS_FAST, MODEL_SONNET, MODEL_HAIKU],
    "openai":     ["gpt-5.5", "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano"],
    "gemini":     ["gemini-3.5-pro", "gemini-3.5-flash", "gemini-3-pro", "gemini-3-flash"],
    "xai":        ["grok-4-latest", "grok-4.3", "grok-4-mini", "grok-code-fast", "grok-3"],
    "deepseek":   ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro", "deepseek-v4-flash"],
    "moonshot":   ["kimi-k2", "kimi-k1.5", "moonshot-v1-128k"],
    "openrouter": ["minimax/minimax-m2.5", "qwen/qwen3-coder-next"],
    "ollama":     ["qwen3-coder-next", "qwen3-32b", "llama-4-maverick"],
}

PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic (Claude)", "openai": "OpenAI", "gemini": "Google Gemini",
    "xai": "xAI (Grok)", "deepseek": "DeepSeek", "moonshot": "Moonshot",
    "openrouter": "OpenRouter", "ollama": "Ollama (local)",
}


def catalog_specs() -> list[tuple[str, str]]:
    """Every built-in model as ``(spec, provider_label)``. Anthropic ids stay
    bare (the default provider); others carry the ``provider:`` prefix the
    resolver expects. The dashboard merges ``[models] catalog`` on top."""
    out: list[tuple[str, str]] = []
    for provider, ids in MODEL_CATALOG.items():
        plabel = PROVIDER_LABELS.get(provider, provider)
        for mid in ids:
            spec = mid if provider == "anthropic" else f"{provider}:{mid}"
            out.append((spec, plabel))
    return out


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


def _resolve_model_for_role(role: str) -> str:
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
    # Dashboard-pinned model (set from the settings page; lives in
    # ~/.maverick/runtime-overrides.toml, never config.toml). A per-role pin
    # wins over the global default pin. Below the user's config.toml [models]
    # above, above the built-in ROLE_MODELS defaults -- an explicit UI choice
    # that still yields to a more specific config [models].<role>.
    try:
        from .runtime_overrides import default_model_override, role_model_override
        pinned = role_model_override(role) or default_model_override()
        if pinned:
            return pinned
    except Exception:  # pragma: no cover -- never let the overlay break resolution
        pass
    # Local-first (opt-in, off by default). When [system] local_first is on and
    # a configured local model's server is reachable, keep the work on-machine;
    # returns None otherwise, so this is a no-op for the default install and
    # gracefully falls through to remote.
    try:
        from .provider_local_first import pick_local
        local = pick_local(role)
        if local:
            return local
    except Exception:  # pragma: no cover -- never let local-first break resolution
        pass
    # Cost-aware routing (opt-in, off by default). pick() returns None when
    # disabled or when no provider is configured, so this is a no-op for the
    # default install.
    try:
        from .cost.router import pick, signal_for_role
        routed = pick(signal_for_role(role))
        if routed:
            return routed
    except Exception:  # pragma: no cover -- never let routing break resolution
        pass
    final = ROLE_MODELS.get(role, DEFAULT_MODEL)
    # Energy-aware downgrade (opt-in, off by default): on a laptop low on
    # battery, step the default-tier model down (Opus->Sonnet->Haiku) to extend
    # runtime, then revert on wall power. No-op unless [routing] energy_aware is
    # on AND battery is low, and only on the default path -- an explicit
    # override/config/router choice above is never downgraded.
    try:
        from .energy_aware_router import route as _energy_route
        cheaper = _cheaper_model(final)
        if cheaper != final:
            final = _energy_route(final, cheaper)
    except Exception:  # pragma: no cover -- never let energy routing break resolution
        pass
    return final


def model_for_role(role: str) -> str:
    """Resolve the model for ``role`` (see ``_resolve_model_for_role``), then
    enforce the admin allow-list: if one is set and the resolved model isn't in
    it, fall back to an allowed model (DEFAULT_MODEL if allowed, else the first).
    A hard cap -- a config.toml or env pin outside the allow-list can't run."""
    final = _resolve_model_for_role(role)
    try:
        from .runtime_overrides import allowed_models
        allow = allowed_models()
        if allow and final not in allow:
            final = DEFAULT_MODEL if DEFAULT_MODEL in allow else sorted(allow)[0]
    except Exception:  # pragma: no cover -- allow-list never breaks resolution
        pass
    return final


def _record_provider_call(provider: str) -> None:
    """Feed the proactive rate-limit predictor one call timestamp. Cheap
    in-memory ring buffer; powers ``maverick diag ratelimits`` and lets the
    predictor estimate wait-before-429. Never raises into the dispatch path."""
    try:
        from .rate_limit_predictor import record
        record(provider)
    except Exception:  # pragma: no cover -- prediction never blocks a call
        pass


def _feed_circuit(provider: str, error: bool) -> None:
    """Record a provider call's outcome on its circuit breaker so repeated
    failures trip it (observable via ``maverick diag circuits``). Observe-only
    here -- it does not short-circuit the call path. Never raises."""
    try:
        from .circuit_breaker import get
        br = get(f"llm:{provider}")
        br.record_failure() if error else br.record_success()
    except Exception:  # pragma: no cover -- breaker never blocks a call
        pass


def _hedge_ms() -> float | None:
    """Tail-latency hedging delay (ms): opt-in, default OFF.

    When set, ``complete_async`` fires a *backup* request this many ms after the
    primary and takes whichever succeeds first, cancelling the laggard — the
    "tail at scale" hedge for tightening p99 on a provider with variable latency.
    It trades extra spend on slow calls for latency, so it is off unless an
    operator opts in via ``MAVERICK_LLM_HEDGE_MS`` or ``[latency] hedge_ms``.
    Returns the delay in ms, or ``None`` (disabled / non-positive / unparseable),
    in which case the single-call path runs unchanged.
    """
    raw: object = os.environ.get("MAVERICK_LLM_HEDGE_MS")
    if raw is None or str(raw).strip() == "":
        try:
            from .config import load_config
            raw = (load_config() or {}).get("latency", {}).get("hedge_ms")
        except Exception:  # pragma: no cover -- config is best-effort here
            raw = None
    if raw is None or str(raw).strip() == "":
        return None
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _cheaper_model(model: str) -> str:
    """One tier cheaper for energy-aware downgrade: Opus->Sonnet->Haiku."""
    if model == MODEL_OPUS or model == MODEL_OPUS_FAST:
        return MODEL_SONNET
    if model == MODEL_SONNET:
        return MODEL_HAIKU
    return model


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
    from .config import PROVIDER_KEY_ENV_MAP
    for env_key in PROVIDER_KEY_ENV_MAP.get(provider, ()):
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


def _release_budget_hold(budget: Budget | None, held: float) -> None:
    if budget is not None and held:
        budget.release(held)


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


def _response_call_cost(model_id, resp) -> float | None:
    """Per-call $ derived from THIS response's own token usage, or ``None`` when
    the response carries no usage to price from.

    provider-health spend used to be diffed off the shared ``budget.dollars``
    counter (``dollars - _d0``), which races other concurrent sub-agents on the
    same budget: their spend lands inside the window and inflates this call's
    recorded dollars. Pricing the response's own usage is call-local, so a wide
    parallel fan-out records each call's real cost. Returns ``None`` when no
    usage is exposed so the caller can fall back to the (sequentially-correct)
    budget diff rather than recording a phantom $0.
    """
    if resp is None:
        return None
    from .budget import (
        _CACHE_READ_MULT,
        _cache_write_mult_from_ttl,
        _lookup_price,
    )
    usage = getattr(getattr(resp, "raw", None), "usage", None)

    def _u(*names) -> int:
        for n in names:
            v = getattr(usage, n, None) if usage is not None else None
            if v is not None:
                try:
                    return max(0, int(v))
                except (TypeError, ValueError):
                    return 0
        return 0

    # Anthropic uses input/output_tokens; OpenAI-compat uses prompt/completion.
    # ``input_tokens`` is non-cached input only; cache tokens are billed apart.
    in_tok = _u("input_tokens", "prompt_tokens")
    out_tok = _u("output_tokens", "completion_tokens")
    cache_read = int(getattr(resp, "cache_read_tokens", 0) or 0)
    cache_write = int(getattr(resp, "cache_creation_tokens", 0) or 0)
    if not (in_tok or out_tok or cache_read or cache_write):
        return None
    in_rate, out_rate = _lookup_price(model_id)
    write_mult = _cache_write_mult_from_ttl(None)
    cost = (in_tok / 1_000_000) * in_rate
    cost += (cache_read / 1_000_000) * in_rate * _CACHE_READ_MULT
    cost += (cache_write / 1_000_000) * in_rate * write_mult
    cost += (out_tok / 1_000_000) * out_rate
    return cost


def _call_spend(model_id, resp, budget, dollars_baseline) -> float:
    """Dollars to attribute to one LLM call for provider-health/metrics.

    Prefers the response's own usage (call-local, race-free under a shared
    budget); falls back to the budget diff when the response exposes no usage.
    """
    if not budget:
        return 0.0
    call_cost = _response_call_cost(model_id, resp)
    return call_cost if call_cost is not None else (budget.dollars - dollars_baseline)


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
                # [providers.<name>] base_url: the CLI preflight already
                # accepts this config key as "a configured provider"; plumb it
                # into the client too. It used to be read by the preflight and
                # then dropped, so a self-hosted setup configured only via
                # config dialed the client's env-var/localhost default and
                # died with "Couldn't reach the LLM provider".
                base_url = None
                default_headers = None
                try:
                    from .config import get_provider_config
                    pcfg = get_provider_config(provider) or {}
                    bu = pcfg.get("base_url")
                    if isinstance(bu, str) and bu.strip():
                        base_url = bu.strip()
                    # Data-residency / ZDR: operator-set extra request headers a
                    # compliance gateway enforces. Accept only a str->str dict.
                    dh = pcfg.get("default_headers")
                    if isinstance(dh, dict):
                        clean = {str(k): str(v) for k, v in dh.items()
                                 if isinstance(k, str)}
                        if clean:
                            default_headers = clean
                except Exception:  # pragma: no cover -- config read fails soft
                    base_url = None
                use_api_provider = (
                    provider in KNOWN_PROVIDERS
                    and (not is_session_provider(provider) or key)
                )
                if use_api_provider or key:
                    self._clients[provider] = get_provider_client(
                        provider, api_key=key, base_url=base_url,
                        default_headers=default_headers,
                    )
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
                        self._clients[provider] = get_provider_client(
                            provider, api_key=key, base_url=base_url,
                            default_headers=default_headers,
                        )
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
        effort: str | None = None,
        _no_failover: bool = False,
    ) -> LLMResponse:
        # Provider failover (opt-in, default off): when a fallback chain is
        # configured for this model, try each in turn. No chain -> this block is
        # skipped and the original single-call path below runs unchanged.
        if not _no_failover:
            from .failover_policy import order_chain, policy_should_retry
            from .provider_failover import failover, fallback_models
            _chain = fallback_models(model or self.model)
            if _chain:
                # The policy engine narrows WHICH errors fail over and skips
                # cooling-down models; with no [provider_failover.policy] both
                # collapse to the v1 behavior.
                return failover([
                    (m, (lambda m=m: self.complete(
                        system, messages, tools=tools, budget=budget,
                        max_tokens=max_tokens, thinking_budget=thinking_budget,
                        model=m, on_delta=on_delta, effort=effort, _no_failover=True)))
                    for m in order_chain([model or self.model, *_chain])
                ], should_retry=policy_should_retry)
        provider, model_id = _parse_spec(model or self.model)
        # Egress lock (no-op unless enterprise mode is on): refuse to send data to a
        # non-local provider so sensitive data never leaves the boundary. Raises
        # EgressBlocked before any prompt is dispatched.
        from .enterprise import assert_provider_allowed
        assert_provider_allowed(provider)
        # Outbound data-minimization (opt-in, default off): strip detectable
        # PII/secrets from the prompt before it leaves the box to a cloud
        # provider. No-op unless [privacy] redact_egress is on; skipped for
        # local providers. Rewrites the outbound copy only.
        from .privacy_egress import maybe_redact_egress
        system, messages = maybe_redact_egress(provider, system, messages)
        _record_provider_call(provider)
        _run_preflight(model_id, system, messages, tools, max_tokens)
        client = self._get_client(provider)
        kwargs: dict[str, Any] = dict(
            system=system, messages=messages, tools=tools, budget=budget,
            max_tokens=max_tokens, thinking_budget=thinking_budget, model=model_id,
        )
        if on_delta is not None and provider == "anthropic":
            kwargs["on_delta"] = on_delta
        # Per-role effort is an Anthropic-only output_config knob; other
        # providers don't accept it, so only thread it to the anthropic provider.
        if effort and provider == "anthropic":
            from .effort import effort_for_model
            model_effort = effort_for_model(effort, model_id)
            if model_effort:
                kwargs["effort"] = model_effort
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
        _resp = None
        # Hold this call's projected cost against the cap BEFORE dispatching, so
        # concurrent callers on a shared budget can't each pass an individual
        # check() and then collectively overshoot -- the same defense the async
        # path uses. reserve() raises BudgetExceeded if the call won't fit;
        # released in `finally` once the actual spend lands.
        _est_cost = _estimate_call_cost(model_id, system, messages, tools, max_tokens)
        _held = budget.reserve(_est_cost) if budget is not None else 0.0
        try:
            with _trace_span(
                _gen_ai_span_name("chat", model_id),
                attributes={
                    "llm.provider": provider, "llm.model": model_id,
                    **_gen_ai_attributes(provider, model_id),
                },
            ):
                _resp = client.complete(**kwargs)
                return _resp
        except Exception:
            _err = True
            raise
        finally:
            if _held:
                budget.release(_held)
            _dt_ms = (_time.time() - _t0) * 1000.0
            # Price THIS call's own usage rather than diffing the shared
            # budget.dollars counter, which races concurrent sub-agents.
            _spent = _call_spend(model_id, _resp, budget, _d0)
            try:
                from .provider_health import get as _h
                _h().record(provider, model_id,
                            latency_ms=_dt_ms, dollars=_spent, error=_err)
            except Exception:  # pragma: no cover -- never fail on stats
                pass
            _feed_circuit(provider, _err)
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
        effort: str | None = None,
        _no_failover: bool = False,
    ) -> LLMResponse:
        # Provider failover (opt-in, default off) — see complete(). No configured
        # chain -> skipped, and the original single-call path below is unchanged.
        if not _no_failover:
            from .failover_policy import order_chain, policy_should_retry
            from .provider_failover import afailover, fallback_models
            _chain = fallback_models(model or self.model)
            if _chain:
                return await afailover([
                    (m, (lambda m=m: self.complete_async(
                        system, messages, tools=tools, budget=budget,
                        max_tokens=max_tokens, thinking_budget=thinking_budget,
                        model=m, effort=effort, _no_failover=True)))
                    for m in order_chain([model or self.model, *_chain])
                ], should_retry=policy_should_retry)
        provider, model_id = _parse_spec(model or self.model)
        # Egress lock (no-op unless enterprise mode is on): see complete().
        from .enterprise import assert_provider_allowed
        assert_provider_allowed(provider)
        # Outbound data-minimization (opt-in, default off): strip detectable
        # PII/secrets from the prompt before it leaves the box to a cloud
        # provider. No-op unless [privacy] redact_egress is on; skipped for
        # local providers. Rewrites the outbound copy only.
        from .privacy_egress import maybe_redact_egress
        system, messages = maybe_redact_egress(provider, system, messages)
        _record_provider_call(provider)
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
        _resp = None
        # Hold this call's projected cost against the cap BEFORE dispatching, so
        # concurrent sub-agents on a shared budget can't each pass an individual
        # check and then collectively overshoot (a $2.50 cap reached $6+ with a
        # wide parallel fan-out). reserve() raises BudgetExceeded here if the
        # call won't fit; released in `finally` once the actual spend lands.
        _est_cost = _estimate_call_cost(model_id, system, messages, tools, max_tokens)
        _held = budget.reserve(_est_cost) if budget is not None else 0.0
        try:
            with _trace_span(
                _gen_ai_span_name("chat", model_id),
                attributes={
                    "llm.provider": provider, "llm.model": model_id,
                    **_gen_ai_attributes(provider, model_id),
                },
            ):
                _ekw = {}
                if effort and provider == "anthropic":
                    from .effort import effort_for_model
                    model_effort = effort_for_model(effort, model_id)
                    if model_effort:
                        _ekw["effort"] = model_effort

                def _call():
                    return client.complete_async(
                        system=system, messages=messages, tools=tools, budget=budget,
                        max_tokens=max_tokens, thinking_budget=thinking_budget,
                        model=model_id, **_ekw,
                    )

                hedge = _hedge_ms()
                if hedge is None:
                    _resp = await _call()
                    return _resp
                # Tail-latency hedge (opt-in): race the primary against a backup
                # fired `hedge` ms later; first success wins, the laggard is
                # cancelled. The race is bounded by the remaining wall budget via
                # a SpanBudget so a hedge can never run past the goal's wall cap,
                # and the remaining budget is stamped on the current trace span.
                import asyncio as _asyncio

                from .latency_best_of_n import AllAttemptsFailed, race_first_success
                from .latency_span_budget import SpanBudget, tag_span_budget

                race_budget_ms: float | None = None
                if budget is not None and budget.max_wall_seconds:
                    span = SpanBudget(
                        max(0.0, (budget.max_wall_seconds - budget.elapsed()) * 1000.0)
                    )
                    tag_span_budget(span)
                    race_budget_ms = span.remaining() or None

                async def _backup():
                    await _asyncio.sleep(hedge / 1000.0)
                    _backup_held = (
                        budget.reserve(_est_cost) if budget is not None else 0.0
                    )
                    try:
                        return await _call()
                    finally:
                        _release_budget_hold(budget, _backup_held)

                try:
                    _resp = await race_first_success(
                        [_call, _backup], budget_ms=race_budget_ms
                    )
                    return _resp
                except AllAttemptsFailed as e:
                    # Both the primary and the hedge failed: surface the real
                    # provider error (chained as __cause__) so failover/retry
                    # classification upstream sees the provider's exception, not
                    # the race wrapper.
                    raise (e.__cause__ or e) from None
        except Exception:
            _err = True
            raise
        finally:
            if _held:
                budget.release(_held)
            _dt_ms = (_time.time() - _t0) * 1000.0
            # Price THIS call's own usage rather than diffing the shared
            # budget.dollars counter, which races concurrent sub-agents.
            _spent = _call_spend(model_id, _resp, budget, _d0)
            try:
                from .provider_health import get as _h
                _h().record(provider, model_id,
                            latency_ms=_dt_ms, dollars=_spent, error=_err)
            except Exception:  # pragma: no cover
                pass
            _feed_circuit(provider, _err)
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

    def prewarm(
        self,
        system: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        *,
        budget: Budget | None = None,
    ) -> bool:
        """Pre-warm the prompt cache for ``(system, tools, model)``.

        Anthropic-only (other providers cache implicitly with no warm hook), and
        a no-op unless caching is on. When a budget is provided, reserve an
        estimated cache-write cost before sending and let the provider record
        returned usage. Returns whether a warm request was sent; never raises."""
        if os.environ.get("MAVERICK_CACHE_MESSAGES", "1") == "0":
            return False
        provider, model_id = _parse_spec(model or self.model)
        if provider != "anthropic":
            return False
        try:
            from .enterprise import assert_provider_allowed
            assert_provider_allowed(provider)
            client = self._get_client(provider)
            warm = getattr(client, "prewarm", None)
            if not callable(warm):
                return False
            messages = [{"role": "user", "content": "warmup"}]
            # A prewarm can bill prompt-cache creation/read tokens even though
            # max_tokens=0. Reserve the worst-case Anthropic cache-write input
            # multiplier before dispatch so zero/low dollar caps cannot be
            # bypassed by opt-in prewarming. The provider records exact usage.
            _held = budget.reserve(
                _estimate_call_cost(model_id, system, messages, tools, 0)
                * _cache_write_mult_from_ttl("1h")
            ) if budget is not None else 0.0
            try:
                if budget is not None:
                    return bool(warm(system, tools, model_id, budget=budget))
                return bool(warm(system, tools, model_id))
            finally:
                if _held:
                    budget.release(_held)
        except Exception:  # pragma: no cover -- prewarm is best-effort
            return False


def cache_prewarm_enabled() -> bool:
    """Opt-in, default-OFF. ``MAVERICK_CACHE_PREWARM=1`` or ``[cache] prewarm =
    true`` pre-warms the prompt cache at orchestrator start so the first turn's
    time-to-first-token doesn't pay the cold cache write."""
    _true = {"1", "true", "yes", "on"}
    if os.environ.get("MAVERICK_CACHE_PREWARM", "").strip().lower() in _true:
        return True
    try:
        from .config import load_config
        v = (load_config() or {}).get("cache", {}).get("prewarm")
        return str(v).strip().lower() in _true if isinstance(v, str) else bool(v)
    except Exception:  # pragma: no cover
        return False
