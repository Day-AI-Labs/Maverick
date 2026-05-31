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


# (provider, model_id, tier, $/Mtok input, $/Mtok output)
_PRICING: list[tuple[str, str, int, float, float]] = [
    # Anthropic
    ("anthropic", "claude-haiku-4-5-20251001",  TIER_CHEAP,   0.80,  4.00),
    ("anthropic", "claude-sonnet-4-6",          TIER_BASE,    3.00, 15.00),
    ("anthropic", "claude-opus-4-8",            TIER_PREMIUM, 5.00, 25.00),
    # Prior Opus kept so price_for_model still resolves a pinned 4-7
    # (same $5/$25). Selection prefers 4-8 above (equal cost, listed first).
    ("anthropic", "claude-opus-4-7",            TIER_PREMIUM, 5.00, 25.00),
    # OpenAI
    ("openai",    "gpt-5-nano",                 TIER_CHEAP,   0.50,  2.50),
    ("openai",    "gpt-5",                      TIER_BASE,    3.00, 12.00),
    ("openai",    "gpt-5-pro",                  TIER_PREMIUM, 8.00, 40.00),
    # DeepSeek
    ("deepseek",  "deepseek-chat",              TIER_CHEAP,   0.14,  0.28),
    ("deepseek",  "deepseek-reasoner",          TIER_BASE,    0.55,  2.19),
    # Moonshot / Kimi
    ("moonshot",  "moonshot-v1-128k",           TIER_BASE,    1.20,  3.60),
    # xAI
    ("xai",       "grok-4",                     TIER_BASE,    3.00, 15.00),
    # Gemini
    ("gemini",    "gemini-2.5-flash",           TIER_CHEAP,   0.30,  1.20),
    ("gemini",    "gemini-2.5-pro",             TIER_PREMIUM, 5.00, 20.00),
]


def price_for_model(model_id: str) -> tuple[float, float] | None:
    """Return (in_per_mtok, out_per_mtok) for a model_id from the router's
    pricing table, or None if it isn't listed.

    Budget billing (budget._lookup_price) consults this for models the
    cost-router can SELECT but that aren't in llm.MODEL_PRICES (e.g.
    gpt-5-nano, grok-4, gemini-2.5-*, the date-suffixed Haiku id) so they
    bill at their real rate instead of silently falling back to Sonnet's.
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


def _enabled() -> bool:
    if os.environ.get("MAVERICK_COST_ROUTING", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("routing") or {}
        return bool(cfg.get("cost_aware"))
    except Exception:
        return False


def _provider_available(provider: str) -> bool:
    """Heuristic: the BYOK key for this provider is set.

    Keeps the dependency surface tiny — we don't probe network.
    """
    env_keys = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openai":    ("OPENAI_API_KEY",),
        "deepseek":  ("DEEPSEEK_API_KEY",),
        "moonshot":  ("MOONSHOT_API_KEY",),
        "xai":       ("XAI_API_KEY", "GROK_API_KEY"),
        "gemini":    ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    }
    for var in env_keys.get(provider, ()):
        if os.environ.get(var, "").strip():
            return True
    # Also accept "configured via maverick config" — cheap check.
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("providers") or {}
        key = (cfg.get(provider) or {}).get("api_key")
        return bool(key.strip()) if isinstance(key, str) else bool(key)
    except Exception:
        return False


def _avg_price(in_rate: float, out_rate: float, *, output_heavy: bool) -> float:
    if output_heavy:
        return (in_rate * 0.3) + (out_rate * 0.7)
    return (in_rate + out_rate) / 2.0


def pick(signal: CostSignal) -> str | None:
    """Return ``"provider:model_id"`` or ``None`` to use the default.

    Returning None means: defer to the legacy ``model_for_role()``
    path. The caller MUST treat None as "no opinion".
    """
    if not _enabled():
        return None

    # Tier-filter then cost-sort.
    candidates = [c for c in _PRICING if c[2] >= signal.tier]
    if not candidates:
        return None

    try:
        from .provider_health import get as _health
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
    available.sort(key=_score)
    provider, model, *_ = available[0]
    return f"{provider}:{model}"


__all__ = [
    "CostSignal", "pick", "signal_for_role", "price_for_model",
    "TIER_CHEAP", "TIER_BASE", "TIER_PREMIUM",
]
