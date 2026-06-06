"""MiniMax M2.5 (and peer cheap open models) are priced and routable via the
existing OpenRouter provider.

Operationalizes the cost lever from the competitive analysis: a cheap open
model that's near-frontier on coding. These tests pin that:
  - MiniMax M2.5 is priced under the key form the runtime lookup actually
    hits (the OpenRouter `vendor/model` id, after the `openrouter:` prefix is
    stripped) -- so spend bills accurately instead of at the Sonnet fallback;
  - the cost router CONSIDERS MiniMax at the cheap tier when OpenRouter is
    configured and routing is opted in;
  - none of this changes default model selection (additive / opt-in).

Hermetic: no network, no real config. Env is scrubbed so only the keys a test
sets are visible to the router's availability heuristic.
"""
from __future__ import annotations

import pytest

# OpenRouter `vendor/model` id for MiniMax M2.5. This is the bare model_id
# _lookup_price sees after stripping the `openrouter:` prefix, so it must be
# the MODEL_PRICES key too.
MINIMAX_ID = "minimax/minimax-m2.5"
MINIMAX_SPEC = f"openrouter:{MINIMAX_ID}"


@pytest.fixture
def _clean(monkeypatch):
    monkeypatch.delenv("MAVERICK_COST_ROUTING", raising=False)
    for prov in (
        "ANTHROPIC", "OPENAI", "DEEPSEEK", "MOONSHOT",
        "XAI", "GEMINI", "GOOGLE", "OPENROUTER",
    ):
        monkeypatch.delenv(f"{prov}_API_KEY", raising=False)
    for role in ("CODER", "ORCHESTRATOR", "SUMMARIZER"):
        monkeypatch.delenv(f"MAVERICK_MODEL_OVERRIDE_{role}", raising=False)
    monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE", raising=False)
    # Point HOME at a tmp with no config so get_role_model returns None.
    monkeypatch.setenv("HOME", "/nonexistent-minimax-routing-test")


def test_minimax_is_priced_in_model_prices():
    from maverick.llm import MODEL_PRICES
    assert MINIMAX_ID in MODEL_PRICES
    in_rate, out_rate = MODEL_PRICES[MINIMAX_ID]
    # Cheap near-frontier: well under flagship rates, sane ordering.
    assert 0 < in_rate < out_rate < 5.0


def test_lookup_price_resolves_openrouter_spec():
    # The router emits "openrouter:vendor/model"; budget billing must resolve
    # it (splitting on the FIRST colon) to the MODEL_PRICES rate, not the
    # Sonnet fallback.
    from maverick.budget import _FALLBACK_PRICE_IN, _lookup_price
    from maverick.llm import MODEL_PRICES

    priced = _lookup_price(MINIMAX_SPEC)
    assert priced is not None
    assert priced == MODEL_PRICES[MINIMAX_ID]
    assert priced[0] != _FALLBACK_PRICE_IN  # not silently the fallback


def test_minimax_in_router_cheap_tier():
    from maverick import cost_router
    rows = [
        r for r in cost_router._PRICING
        if r[0] == "openrouter" and r[1] == MINIMAX_ID
    ]
    assert rows, "MiniMax M2.5 missing from the cost router's OpenRouter tier"
    assert rows[0][2] == cost_router.TIER_CHEAP


def test_router_considers_minimax_when_openrouter_configured(_clean, monkeypatch):
    # Opt in to cost routing with ONLY OpenRouter keyed. summarizer is the
    # cheap-tier role, so the router must pick an OpenRouter model.
    monkeypatch.setenv("MAVERICK_COST_ROUTING", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    from maverick.llm import model_for_role

    got = model_for_role("summarizer")
    assert got.startswith("openrouter:"), got


def test_off_by_default_does_not_select_openrouter(_clean, monkeypatch):
    # Routing disabled (default): MiniMax is registered but never selected;
    # the static ROLE_MODELS default wins. Additive change, no behaviour drift.
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    from maverick.llm import ROLE_MODELS, model_for_role

    assert model_for_role("summarizer") == ROLE_MODELS["summarizer"]
