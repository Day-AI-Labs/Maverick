"""Provider-key entry + capability/feature toggles via the dashboard config
overlay (~/.maverick/dashboard-config.toml, deep-merged in config.load_config).
Neither path touches config.toml. (Per-role models live in the separate runtime
overlay shipped by #1319.)"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _no_provider_env(monkeypatch):
    from maverick import config
    for v in config.PROVIDER_KEY_ENV_VARS + config.PROVIDER_BASE_URL_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    for v in ("GOOGLE_API_KEY", "GROK_API_KEY"):
        monkeypatch.delenv(v, raising=False)


def test_provider_key_overlay_unblocks(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _no_provider_env(monkeypatch)
    from maverick import config
    from maverick_dashboard import settings_store
    assert config.any_provider_configured() is False
    settings_store.set_provider("anthropic", api_key="sk-test-123456")  # pragma: allowlist secret
    assert config.dashboard_overrides_path().exists()
    assert not config.config_path().exists()            # config.toml untouched
    assert config.any_provider_configured() is True
    assert config.get_provider_config("anthropic")["api_key"] == "sk-test-123456"  # pragma: allowlist secret
    settings_store.clear_provider("anthropic")
    assert config.any_provider_configured() is False


def test_toggle_overlay_reflected(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import config
    from maverick_dashboard import settings_store
    assert config.get_capabilities()["web_search"] is False
    settings_store.set_toggle("capabilities", "web_search", True)
    assert config.get_capabilities()["web_search"] is True
    settings_store.set_toggle("features", "skills", False)
    assert config.get_features()["skills"] is False


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    return TestClient(dash_app.app, headers={"Origin": "http://testserver"})


def test_settings_page_has_provider_entry_and_toggles(monkeypatch, tmp_path):
    _no_provider_env(monkeypatch)
    c = _client(monkeypatch, tmp_path)
    r = c.get("/settings")
    assert r.status_code == 200
    assert 'action="/settings/providers"' in r.text      # editable key entry
    assert 'action="/settings/capabilities"' in r.text    # capability toggles
    assert 'name="web_search"' in r.text


def test_provider_post_redacts_and_persists(monkeypatch, tmp_path):
    _no_provider_env(monkeypatch)
    c = _client(monkeypatch, tmp_path)
    from maverick import config
    assert c.post("/settings/providers",
                  data={"provider": "openai", "api_key": "sk-secret-abcd9999"}).status_code == 200  # pragma: allowlist secret
    assert config.get_provider_config("openai")["api_key"] == "sk-secret-abcd9999"  # pragma: allowlist secret
    body = c.get("/settings").text
    assert "sk-secret-abcd9999" not in body  # pragma: allowlist secret  (raw key never echoed)
    assert "9999" in body                                # only the masked hint


def test_toggle_endpoints(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from maverick import config
    assert c.post("/settings/capabilities", data={"browser": "on"}).status_code == 200
    assert config.get_capabilities()["browser"] is True
    # an unchecked box is omitted from the form -> deactivated on save
    assert c.post("/settings/capabilities", data={}).status_code == 200
    assert config.get_capabilities()["browser"] is False


def test_concurrent_provider_and_toggle_both_apply(monkeypatch, tmp_path):
    """A set_provider racing a set_toggle (different sections of one overlay
    file) must not have either change clobbered by a stale re-read."""
    import threading

    monkeypatch.setenv("HOME", str(tmp_path))
    _no_provider_env(monkeypatch)
    from maverick_dashboard import settings_store

    barrier = threading.Barrier(2)

    def do_provider():
        barrier.wait()
        settings_store.set_provider("anthropic", api_key="sk-test-abc123")  # pragma: allowlist secret

    def do_toggle():
        barrier.wait()
        name = next(iter(settings_store.FEATURE_DEFAULTS))
        settings_store.set_toggle("features", name, True)

    ts = [threading.Thread(target=do_provider), threading.Thread(target=do_toggle)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    overlay = settings_store.load_overlay()
    assert overlay.get("providers", {}).get("anthropic", {}).get("api_key")
    name = next(iter(settings_store.FEATURE_DEFAULTS))
    assert overlay.get("features", {}).get(name) is True
