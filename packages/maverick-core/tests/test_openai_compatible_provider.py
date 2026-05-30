"""Generic OpenAI-compatible provider (base_url-driven).

Selecting provider "openai-compatible" (alias "custom") with a
configured base_url must construct an OpenAIClient pointed at that
base_url. The network is mocked via a fake ``openai`` module, so no
real calls are made.
"""
from __future__ import annotations

import sys
import types

import pytest


class _FakeOpenAIClient:
    """Stand-in for openai.OpenAI / AsyncOpenAI — records the base_url."""

    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key = api_key
        self.base_url = base_url


@pytest.fixture
def fake_openai(monkeypatch):
    fake = types.ModuleType("openai")
    fake.OpenAI = _FakeOpenAIClient
    fake.AsyncOpenAI = _FakeOpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake)
    # Isolate from any ambient config/env on the test host.
    monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    return fake


def test_registered_in_provider_registry():
    """Registry membership + aliases resolve without instantiating."""
    from maverick.providers import KNOWN_PROVIDERS, _canonical
    assert "openai_compatible" in KNOWN_PROVIDERS
    assert _canonical("openai-compatible") == "openai_compatible"
    assert _canonical("custom") == "openai_compatible"


def test_base_url_from_env_passthrough(fake_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "gsk-secret")
    from maverick.providers import get_provider_client
    from maverick.providers.openai_compatible_provider import OpenAICompatibleClient

    client = get_provider_client("openai-compatible")
    assert isinstance(client, OpenAICompatibleClient)
    # base_url passed through verbatim to the underlying OpenAI SDK client.
    assert client._sync.base_url == "https://api.groq.com/openai/v1"
    assert client._async.base_url == "https://api.groq.com/openai/v1"
    assert client._sync.api_key == "gsk-secret"


def test_custom_alias_dispatches(fake_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    # A custom base_url requires its own key -- the client refuses to leak
    # OPENAI_API_KEY to an arbitrary endpoint, so supply OPENAI_COMPATIBLE_API_KEY.
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-local")
    from maverick.providers import get_provider_client
    from maverick.providers.openai_compatible_provider import OpenAICompatibleClient

    client = get_provider_client("custom")
    assert isinstance(client, OpenAICompatibleClient)
    assert client._sync.base_url == "http://localhost:1234/v1"
    assert client._sync.api_key == "sk-local"


def test_base_url_from_config(fake_openai, monkeypatch, tmp_path):
    """[providers.openai_compatible] base_url drives the client, with
    ${VAR} interpolation in the api_key (matches config.py contract)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[providers.openai_compatible]\n"
        'base_url = "https://api.together.xyz/v1"\n'
        'api_key = "${MY_TOGETHER_KEY}"\n'
    )
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    monkeypatch.setenv("MY_TOGETHER_KEY", "tok-from-env")
    from maverick.providers.openai_compatible_provider import OpenAICompatibleClient

    client = OpenAICompatibleClient()
    assert client._sync.base_url == "https://api.together.xyz/v1"
    assert client._sync.api_key == "tok-from-env"


def test_missing_base_url_raises(fake_openai):
    """No base_url anywhere is a configuration error, not a silent default."""
    from maverick.providers.openai_compatible_provider import OpenAICompatibleClient
    with pytest.raises(ValueError) as exc:
        OpenAICompatibleClient()
    assert "base_url" in str(exc.value)
