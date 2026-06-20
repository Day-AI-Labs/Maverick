"""Cross-provider cost-aware router.

The existing ``maverick.routing`` cascade picks Anthropic Haiku /
Sonnet / Opus based on signal. This module sits next to it and picks
*provider* — i.e. given a role, which provider/model combination
hits the cheapest viable rate?

Useful when the user has multiple BYOK adapters configured. We pick:

  1. The user's explicit role override (config wins, always).
  2. Otherwise: among configured + healthy providers, the cheapest
     one that exposes a model at the chosen capability tier.
  3. Tie-break by recent error rate (provider_health snapshot).
  4. Final fallback: ``model_for_role(role)`` from llm.py.

Opt-in. Off by default; flipped on via ``MAVERICK_COST_ROUTING=1``
or ``[routing] cost_aware = true`` in config.

Per-million pricing (input + output averaged) is the table in
``_PRICING``. Numbers are May 2026 list rates; off when wrong but
correctable in one place.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


# Capability tiers; higher = stronger. Picker may upgrade tier when
# the signal demands it (verifier confidence low, retry, thinking).
TIER_CHEAP = 0
TIER_BASE = 1
TIER_PREMIUM = 2


# (provider, model_id, tier). The per-million input/output rates are NOT
# duplicated here: llm.MODEL_PRICES is the single billing source of truth, so
# the router derives every rate from it via _rate_for() below. Earlier the
# table hard-coded its own numbers AND its own model ids (gpt-5*, grok-4,
# gemini-2.5-*, a date-suffixed Haiku) that didn't exist in MODEL_PRICES — they
# scored against stale rates and billed at the Sonnet fallback. Every id here
# now resolves in MODEL_PRICES.
_TIERS: list[tuple[str, str, int]] = [
    # Anthropic
    ("anthropic", "claude-haiku-4-5",   TIER_CHEAP),
    ("anthropic", "claude-sonnet-4-6",  TIER_BASE),
    ("anthropic", "claude-opus-4-8",    TIER_PREMIUM),
    # Prior Opus kept so price_for_model still resolves a pinned 4-7
    # (same $5/$25). Selection prefers 4-8 above (equal cost, listed first).
    ("anthropic", "claude-opus-4-7",    TIER_PREMIUM),
    # OpenAI
    ("openai",    "gpt-5.4-nano",       TIER_CHEAP),
    ("openai",    "gpt-5.4",            TIER_BASE),
    ("openai",    "gpt-5.4-pro",        TIER_PREMIUM),
    # DeepSeek
    ("deepseek",  "deepseek-chat",      TIER_CHEAP),
    ("deepseek",  "deepseek-reasoner",  TIER_BASE),
    # Moonshot / Kimi
    ("moonshot",  "moonshot-v1-128k",   TIER_BASE),
    # xAI
    ("xai",       "grok-4-latest",      TIER_BASE),
    # Gemini
    ("gemini",    "gemini-3.5-flash",   TIER_CHEAP),
    ("gemini",    "gemini-3.5-pro",     TIER_PREMIUM),
    # OpenRouter: cheap, near-frontier-on-coding open models. Additive/opt-in —
    # only considered when OPENROUTER_API_KEY (or [providers.openrouter]) is set
    # AND cost routing is enabled. vendor/model ids resolve in llm.MODEL_PRICES.
    ("openrouter", "minimax/minimax-m2.5",     TIER_CHEAP),
    ("openrouter", "deepseek/deepseek-v4-pro", TIER_CHEAP),
    ("openrouter", "qwen/qwen3-coder-next",    TIER_CHEAP),
]


def _rate_for(model_id: str) -> tuple[float, float] | None:
    """(in_per_mtok, out_per_mtok) for a model id from the canonical
    llm.MODEL_PRICES catalog, or None if absent (so a stale tier entry is
    dropped from routing rather than scored against an invented rate)."""
    try:
        from ..llm import MODEL_PRICES
    except ImportError:
        return None
    return MODEL_PRICES.get(model_id)


# (provider, model_id, tier, $/Mtok input, $/Mtok output) — rates pulled from
# llm.MODEL_PRICES at import so there is exactly one place to edit pricing.
_PRICING: list[tuple[str, str, int, float, float]] = [
    (provider, mid, tier, rate[0], rate[1])
    for provider, mid, tier in _TIERS
    if (rate := _rate_for(mid)) is not None
]


def price_for_model(model_id: str) -> tuple[float, float] | None:
    """Return (in_per_mtok, out_per_mtok) for a model_id from the router's
    pricing table, or None if it isn't listed.

    Budget billing (budget._lookup_price) consults this as a secondary
    lookup for any selectable model. Every id in the table now lives in
    llm.MODEL_PRICES (the rates are derived from it), so this resolves to
    the same canonical rate rather than a stale duplicate.
    """
    if not model_id:
        return None
    for _provider, mid, _tier, in_price, out_price in _PRICING:
        if mid == model_id:
            return (in_price, out_price)
    return None


@dataclass
class CostSignal:
    role: str = ""
    tier: int = TIER_BASE
    # Output-heavy roles (revisor) weight output rates more.
    output_heavy: bool = False


# Default capability tier per role. Mirrors the intent of ROLE_MODELS
# (orchestrator/revisor on the strongest model, summarizer on the cheapest)
# but expressed as a provider-agnostic tier the router maps to whichever
# configured provider hits that tier cheapest.
_ROLE_TIERS: dict[str, int] = {
    "orchestrator":    TIER_PREMIUM,
    "revisor":         TIER_PREMIUM,
    "summarizer":      TIER_CHEAP,
    # Everything else (researcher/coder/writer/analyst/verifier/
    # skill_distiller) is solid mid-tier work.
}

# Roles whose value is mostly in the generated output (longer completions),
# so the cost score should weight the output rate more heavily.
_OUTPUT_HEAVY_ROLES = frozenset({"revisor", "writer", "coder"})


def signal_for_role(role: str) -> CostSignal:
    """Build the default CostSignal for a role (tier + output-weighting)."""
    return CostSignal(
        role=role,
        tier=_ROLE_TIERS.get(role, TIER_BASE),
        output_heavy=role in _OUTPUT_HEAVY_ROLES,
    )


# ---- per-role routing policies (cost-aware router v2) ----------------------
#
# [routing.roles.<role>] in config narrows the router for that role only:
#
#   [routing.roles.summarizer]
#   providers = ["deepseek", "openrouter"]   # only these may serve the role
#   deny_providers = ["openai"]              # never these
#   max_price_per_mtok = 1.5                 # cost ceiling (weighted avg rate)
#   tier = "cheap"                           # tier floor override
#
# All keys optional; an absent table leaves v1 behavior untouched.

_TIER_NAMES = {"cheap": TIER_CHEAP, "base": TIER_BASE, "premium": TIER_PREMIUM}


@dataclass(frozen=True)
class RolePolicy:
    providers: frozenset[str] = frozenset()       # empty = unrestricted
    deny_providers: frozenset[str] = frozenset()
    max_price_per_mtok: float | None = None
    tier: int | None = None

    def is_empty(self) -> bool:
        return (not self.providers and not self.deny_providers
                and self.max_price_per_mtok is None and self.tier is None)


def role_policy(role: str) -> RolePolicy:
    """The configured per-role policy (empty policy when unset)."""
    try:
        from ..config import load_config
        roles = (((load_config() or {}).get("routing") or {}).get("roles") or {})
        raw = roles.get(role)
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return RolePolicy()

    def _names(key: str) -> frozenset[str]:
        v = raw.get(key)
        if isinstance(v, (list, tuple, set)):
            return frozenset(str(x).strip().lower() for x in v if str(x).strip())
        return frozenset()

    ceiling = raw.get("max_price_per_mtok")
    if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or ceiling <= 0:
        ceiling = None
    tier = _TIER_NAMES.get(str(raw.get("tier", "")).strip().lower())
    return RolePolicy(
        providers=_names("providers"),
        deny_providers=_names("deny_providers"),
        max_price_per_mtok=float(ceiling) if ceiling is not None else None,
        tier=tier,
    )


def _enabled() -> bool:
    if os.environ.get("MAVERICK_COST_ROUTING", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("routing") or {}
        return bool(cfg.get("cost_aware"))
    except Exception:
        return False


def _allowed_providers() -> set[str] | None:
    """Return the routing provider allowlist, or None when unrestricted.

    The installer writes this list alongside advanced routing flags so those
    opt-ins only use providers the user selected, even if other API keys are
    present in the shell environment. Hand-written configs without the key keep
    the historical unrestricted behavior.
    """
    try:
        from ..config import load_config
        routing = (load_config() or {}).get("routing") or {}
    except Exception:
        return None
    allowed = routing.get("allowed_providers")
    if not isinstance(allowed, list):
        return None
    names = {str(p).strip() for p in allowed if str(p).strip()}
    return names or set()


def _provider_available(provider: str) -> bool:
    """Heuristic: the BYOK key for this provider is set and allowed.

    Keeps the dependency surface tiny — we don't probe network.
    """
    allowed = _allowed_providers()
    if allowed is not None and provider not in allowed:
        return False

    env_keys = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openai":    ("OPENAI_API_KEY",),
        "deepseek":  ("DEEPSEEK_API_KEY",),
        "moonshot":  ("MOONSHOT_API_KEY",),
        "xai":       ("XAI_API_KEY", "GROK_API_KEY"),
        "gemini":    ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "openrouter": ("OPENROUTER_API_KEY",),
    }
    for var in env_keys.get(provider, ()):
        if os.environ.get(var, "").strip():
            return True
    # Also accept "configured via maverick config" — cheap check.
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("providers") or {}
        key = (cfg.get(provider) or {}).get("api_key")
        return bool(key.strip()) if isinstance(key, str) else bool(key)
    except Exception:
        return False


def _avg_price(in_rate: float, out_rate: float, *, output_heavy: bool) -> float:
    if output_heavy:
        return (in_rate * 0.3) + (out_rate * 0.7)
    return (in_rate + out_rate) / 2.0


# A provider whose recent error rate is at/above this is EXCLUDED from
# routing, not merely penalized: the multiplicative error surcharge alone
# let a 100%-error (down) provider still win if it was cheap enough. Knob:
# env MAVERICK_ROUTING_MAX_ERROR_RATE or [routing] max_error_rate; default
# 0.5 (>=50% recent failures => unhealthy, route elsewhere).
_DEFAULT_MAX_ERROR_RATE = 0.5
# Require a minimum sample size before excluding, so a single early failure
# (1/1 = 100%) doesn't blacklist a provider that's actually fine.
_MIN_CALLS_FOR_EXCLUSION = 3


def _max_error_rate() -> float:
    """Recent-error-rate ceiling above which a provider is excluded."""
    raw = os.environ.get("MAVERICK_ROUTING_MAX_ERROR_RATE")
    if raw is None:
        try:
            from ..config import load_config
            routing = (load_config() or {}).get("routing") or {}
            raw = routing.get("max_error_rate")
        except Exception:
            raw = None
    if raw is None:
        return _DEFAULT_MAX_ERROR_RATE
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ERROR_RATE
    # A non-positive or >1 ceiling would exclude everything / nothing in a
    # surprising way; clamp to a sane (0, 1] band, else fall back to default.
    if not (0.0 < val <= 1.0):
        return _DEFAULT_MAX_ERROR_RATE
    return val


def _is_unhealthy(stat: dict | None, threshold: float) -> bool:
    """True if a provider_health snapshot row is over the error ceiling with
    enough recent samples to trust the rate."""
    if not stat:
        return False
    if (stat.get("calls") or 0) < _MIN_CALLS_FOR_EXCLUSION:
        return False
    return (stat.get("error_rate") or 0.0) >= threshold


def pick(signal: CostSignal) -> str | None:
    """Return ``"provider:model_id"`` or ``None`` to use the default.

    Returning None means: defer to the legacy ``model_for_role()``
    path. The caller MUST treat None as "no opinion".
    """
    if not _enabled():
        return None

    # Per-role policy (v2): tier floor override + provider allow/deny + cost
    # ceiling. An unset table is an empty policy and changes nothing.
    policy = role_policy(signal.role) if signal.role else RolePolicy()
    tier = policy.tier if policy.tier is not None else signal.tier

    # Tier-filter then cost-sort.
    candidates = [c for c in _PRICING if c[2] >= tier]
    if policy.providers:
        candidates = [c for c in candidates if c[0] in policy.providers]
    if policy.deny_providers:
        candidates = [c for c in candidates if c[0] not in policy.deny_providers]
    if policy.max_price_per_mtok is not None:
        candidates = [
            c for c in candidates
            if _avg_price(c[3], c[4], output_heavy=signal.output_heavy)
            <= policy.max_price_per_mtok
        ]
    if not candidates:
        return None

    try:
        from ..provider_health import get as _health
        snap = {(r["provider"], r["model"]): r for r in _health().snapshot()}
    except Exception:
        snap = {}

    def _score(row):
        provider, model, _tier, in_rate, out_rate = row
        cost = _avg_price(in_rate, out_rate, output_heavy=signal.output_heavy)
        # Penalize providers with high recent error rate (we want
        # cheap AND working; 10% errors ≈ 1x cost surcharge, 100%
        # errors ≈ 10x surcharge).
        stat = snap.get((provider, model))
        err_rate = (stat.get("error_rate") or 0.0) if stat else 0.0
        err_pen = 1.0 + err_rate * 10.0
        return cost * err_pen

    available = [c for c in candidates if _provider_available(c[0])]
    if not available:
        return None
    # Hard health exclusion: drop any provider/model whose recent error rate
    # is over the threshold (with enough samples to trust it). The error
    # surcharge in _score only multiplies cost, so a cheap-but-down provider
    # could still win; excluding it forces a fallback to the cheapest HEALTHY
    # candidate. If every candidate is unhealthy, keep them all rather than
    # return nothing useful — a degraded pick beats silently routing nowhere.
    threshold = _max_error_rate()
    healthy = [c for c in available if not _is_unhealthy(snap.get((c[0], c[1])), threshold)]
    available = healthy or available
    available.sort(key=_score)
    provider, model, *_ = available[0]
    return f"{provider}:{model}"


__all__ = [
    "CostSignal", "RolePolicy", "pick", "role_policy", "signal_for_role",
    "price_for_model", "TIER_CHEAP", "TIER_BASE", "TIER_PREMIUM",
]
