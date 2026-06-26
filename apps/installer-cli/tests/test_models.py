"""Wizard model-catalog invariants."""
from __future__ import annotations

import pytest
from maverick_installer import models


def test_every_provider_has_required_fields():
    for prov_id, info in models.PROVIDERS.items():
        assert "label" in info, f"{prov_id} missing label"
        assert "status" in info, f"{prov_id} missing status"
        assert info["status"] in ("ready", "planned")
        assert isinstance(info["models"], list)
        assert len(info["models"]) > 0
        for m in info["models"]:
            assert "id" in m
            assert "notes" in m


def test_default_for_every_role():
    for role, _ in models.ROLES:
        spec = models.default_for_role(role)
        assert ":" in spec, f"{role} default missing provider prefix: {spec}"
        provider, _model = spec.split(":", 1)
        assert provider in models.PROVIDERS, f"{role} -> unknown provider {provider}"


def test_all_providers_now_ready():
    # Sanity check: multi-provider dispatch landed; nothing should be 'planned'.
    for prov_id, info in models.PROVIDERS.items():
        assert info["status"] == "ready", (
            f"{prov_id} still marked planned; update models.py"
        )


def test_byok_providers_offered():
    """All 8 BYOK providers must show in the wizard.

    Adding a provider client without exposing it in the wizard is a
    silent regression -- non-technical users have no way to reach it.
    """
    expected = {
        "anthropic", "openai", "moonshot", "xai",
        "gemini", "deepseek", "openrouter", "ollama",
    }
    assert expected.issubset(set(models.PROVIDERS)), (
        f"missing from wizard catalog: {expected - set(models.PROVIDERS)}"
    )


def test_byok_env_vars_set():
    """Every provider that uses an API key must declare its env var.

    Without this, collect_api_keys() silently skips the provider and
    the user ends up with a config that references ${SOMETHING} that
    was never prompted for.
    """
    needs_key = {
        "anthropic":  "ANTHROPIC_API_KEY",
        "openai":     "OPENAI_API_KEY",
        "moonshot":   "MOONSHOT_API_KEY",
        "deepseek":   "DEEPSEEK_API_KEY",
        "xai":        "XAI_API_KEY",
        "gemini":     "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    for prov_id, expected_env in needs_key.items():
        info = models.PROVIDERS[prov_id]
        assert info.get("env") == expected_env, (
            f"{prov_id}: env={info.get('env')!r}, expected {expected_env!r}"
        )
    # Ollama is local-only -- no key.
    assert models.PROVIDERS["ollama"].get("env") is None


def test_openai_compatible_declares_base_url_env():
    info = models.PROVIDERS["openai_compatible"]
    assert info.get("env") == "OPENAI_COMPATIBLE_API_KEY"
    assert "OPENAI_COMPATIBLE_BASE_URL" in info.get("env_vars", [])


def test_wizard_catalog_matches_kernel_registry():
    """The wizard offerings must be dispatchable by the kernel.

    Every provider the wizard shows must be reachable via the BYOK registry
    (maverick.providers.KNOWN_PROVIDERS). If they drift, a user picks a
    provider in the wizard but the kernel refuses to instantiate it -- the
    worst possible UX bug.
    """
    try:
        from maverick.providers import KNOWN_PROVIDERS
    except ImportError:
        pytest.skip("maverick-core not installed in this environment")
    dispatchable = set(KNOWN_PROVIDERS)
    wizard_only = set(models.PROVIDERS) - dispatchable
    assert not wizard_only, (
        f"wizard offers providers the kernel can't dispatch: {wizard_only}"
    )


def test_wizard_model_ids_have_pricing():
    """Every BYOK model id in the wizard should be priced in the kernel.

    A user picks a model -> the agent dispatches it -> budget code looks
    up MODEL_PRICES -> falls back to 0 silently if missing. That hides
    cost from the user. Wizard-offered ids must be priced.

    Exemptions:
      - ollama / openrouter / tgi / openai_compatible: local or
        aggregated or self-hosted catalogs (dynamic, zero per-token
        cost known to the kernel).
    """
    try:
        from maverick.llm import MODEL_PRICES
    except ImportError:
        pytest.skip("maverick-core not installed in this environment")
    unpriced: list[str] = []
    for prov_id, info in models.PROVIDERS.items():
        if prov_id in ("ollama", "openrouter", "tgi", "openai_compatible"):
            continue
        for m in info["models"]:
            if m["id"] not in MODEL_PRICES:
                unpriced.append(f"{prov_id}:{m['id']}")
    assert not unpriced, (
        f"wizard offers models not priced in llm.MODEL_PRICES: {unpriced}"
    )
