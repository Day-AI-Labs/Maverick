"""Enterprise mode: egress lock + fail-closed safety defaults."""
from __future__ import annotations

import pytest
from maverick import capability
from maverick.enterprise import (
    EgressBlocked,
    assert_provider_allowed,
    enterprise_enabled,
    is_local_provider,
)
from maverick.safety import consent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start each test from a known-off state with an empty config."""
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    monkeypatch.delenv("MAVERICK_ENFORCE_CAPABILITIES", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})


def test_off_by_default():
    assert enterprise_enabled() is False


def test_env_enables_and_disables(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    assert enterprise_enabled() is True
    # An explicit falsey env force-disables even if config would enable it.
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "0")
    assert enterprise_enabled() is False


def test_config_enables(monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config", lambda *a, **k: {"enterprise": {"mode": True}}
    )
    assert enterprise_enabled() is True


def test_local_provider_classification():
    assert is_local_provider("ollama")
    assert is_local_provider("local")  # alias -> ollama
    assert is_local_provider("vllm")
    assert is_local_provider("tgi")
    assert is_local_provider("Ollama")  # canonicalized
    assert not is_local_provider("anthropic")
    assert not is_local_provider("openai")


def test_egress_guard_is_noop_when_off():
    # No raise even for a cloud provider when enterprise mode is off.
    assert assert_provider_allowed("anthropic") is None


def test_egress_guard_blocks_cloud_when_on(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    with pytest.raises(EgressBlocked) as exc:
        assert_provider_allowed("anthropic")
    assert exc.value.provider == "anthropic"
    # Self-hosted providers pass.
    assert assert_provider_allowed("ollama") is None
    assert assert_provider_allowed("vllm") is None


def test_extra_local_providers_allow_listed(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"enterprise": {"local_providers": ["myvllm"]}},
    )
    assert is_local_provider("myvllm")
    assert assert_provider_allowed("myvllm") is None
    # Still blocks an un-listed cloud provider.
    with pytest.raises(EgressBlocked):
        assert_provider_allowed("openai")


def test_consent_defaults_fail_closed_in_enterprise(monkeypatch):
    # Off -> auto-approve (unchanged behavior).
    assert consent._resolve_mode() == "auto-approve"
    # On -> ask (fail-closed; non-tty then denies).
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    assert consent._resolve_mode() == "ask"
    # An explicit consent mode still wins over the enterprise default.
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "dashboard")
    assert consent._resolve_mode() == "dashboard"


def test_capabilities_forced_on_in_enterprise(monkeypatch):
    assert capability.capability_enforced() is False
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    assert capability.capability_enforced() is True
