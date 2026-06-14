"""Channel setup from the dashboard: enable/disable + credentials stored in the
overlay (dashboard-config.toml), which load_config() deep-merges so
`maverick serve` picks them up with no config.toml edit."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_ORIGIN = {"origin": "http://testserver"}


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    # MAVERICK_CONFIG anchors both config.toml and its sibling
    # dashboard-config.toml (the overlay settings_store writes) under tmp.
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    yield


# ---- settings_store unit level ------------------------------------------------

def test_set_channel_writes_enabled_and_fields():
    from maverick_dashboard import settings_store as ss
    ss.set_channel("slack", True, {"app_token": "xapp-1", "bot_token": "xoxb-1"})
    overlay = ss.load_overlay()
    assert overlay["channels"]["slack"]["enabled"] is True
    assert overlay["channels"]["slack"]["app_token"] == "xapp-1"


def test_channels_state_masks_secrets():
    from maverick_dashboard import settings_store as ss
    ss.set_channel("slack", True, {"app_token": "xapp-supersecret", "bot_token": "xoxb-1"})
    state = {c["name"]: c for c in ss.channels_state()}
    slack = state["slack"]
    assert slack["enabled"] is True
    f = {x["key"]: x for x in slack["fields"]}
    # secret never echoed back; a masked hint is shown instead
    assert f["app_token"]["value"] == ""
    assert "supersecret" not in f["app_token"]["hint"]
    assert f["app_token"]["hint"]  # some mask present


def test_blank_secret_keeps_existing():
    from maverick_dashboard import settings_store as ss
    ss.set_channel("discord", True, {"bot_token": "keepme"})
    # toggle off without re-entering the token
    ss.set_channel("discord", False, {"bot_token": ""})
    overlay = ss.load_overlay()
    assert overlay["channels"]["discord"]["enabled"] is False
    assert overlay["channels"]["discord"]["bot_token"] == "keepme"


def test_int_field_typed_and_validated():
    from maverick_dashboard import settings_store as ss
    ss.set_channel("sms", True, {"account_sid": "AC1", "auth_token": "t",
                                 "from_number": "+1", "port": "8770"})
    assert ss.load_overlay()["channels"]["sms"]["port"] == 8770
    with pytest.raises(ValueError):
        ss.set_channel("sms", True, {"port": "not-a-number"})


def test_clear_and_unknown_channel():
    from maverick_dashboard import settings_store as ss
    ss.set_channel("telegram", True, {"bot_token": "t"})
    ss.clear_channel("telegram")
    assert "telegram" not in (ss.load_overlay().get("channels") or {})
    with pytest.raises(ValueError):
        ss.set_channel("nope", True, {})
    with pytest.raises(ValueError):
        ss.clear_channel("nope")


def test_overlay_deep_merges_into_load_config():
    from maverick import config
    from maverick_dashboard import settings_store as ss
    ss.set_channel("telegram", True, {"bot_token": "12345:secret"})
    # this is the real wiring proof: server.build_from_config reads load_config()
    merged = config.load_config()
    assert merged["channels"]["telegram"]["enabled"] is True
    assert merged["channels"]["telegram"]["bot_token"] == "12345:secret"


def test_channel_coexists_with_provider_keys():
    from maverick_dashboard import settings_store as ss
    ss.set_provider("anthropic", api_key="sk-ant-xxx")
    ss.set_channel("slack", True, {"app_token": "xapp", "bot_token": "xoxb"})
    overlay = ss.load_overlay()
    # one file, full-state writes: neither clobbers the other
    assert overlay["providers"]["anthropic"]["api_key"] == "sk-ant-xxx"
    assert overlay["channels"]["slack"]["enabled"] is True


# ---- route level --------------------------------------------------------------

def test_page_renders_management_forms():
    r = _client().get("/channels")
    assert r.status_code == 200
    assert 'action="/channels/save"' in r.text
    assert 'value="slack"' in r.text and 'value="telegram"' in r.text
    assert 'name="enabled"' in r.text


def test_save_channel_enables_and_hides_secret():
    c = _client()
    r = c.post("/channels/save", headers=_ORIGIN, follow_redirects=False, data={
        "channel": "slack", "enabled": "on",
        "app_token": "xapp-leak", "bot_token": "xoxb-leak"})
    assert r.status_code == 303
    from maverick_dashboard import settings_store as ss
    assert ss.load_overlay()["channels"]["slack"]["enabled"] is True
    # the secret must never render back on the page
    page = c.get("/channels").text
    assert "xapp-leak" not in page and "xoxb-leak" not in page


def test_save_without_checkbox_disables():
    c = _client()
    c.post("/channels/save", headers=_ORIGIN, data={
        "channel": "telegram", "enabled": "on", "bot_token": "t"})
    # second save omits the checkbox -> disabled, token kept
    r = c.post("/channels/save", headers=_ORIGIN, follow_redirects=False, data={
        "channel": "telegram", "bot_token": ""})
    assert r.status_code == 303
    from maverick_dashboard import settings_store as ss
    ch = ss.load_overlay()["channels"]["telegram"]
    assert ch["enabled"] is False and ch["bot_token"] == "t"


def test_clear_route_removes_channel():
    c = _client()
    c.post("/channels/save", headers=_ORIGIN, data={
        "channel": "discord", "enabled": "on", "bot_token": "t"})
    r = c.post("/channels/clear", headers=_ORIGIN, follow_redirects=False,
               data={"channel": "discord"})
    assert r.status_code == 303
    from maverick_dashboard import settings_store as ss
    assert "discord" not in (ss.load_overlay().get("channels") or {})


def test_invalid_channel_rejected():
    r = _client().post("/channels/save", headers=_ORIGIN, follow_redirects=False,
                       data={"channel": "nope", "enabled": "on"})
    assert r.status_code == 400


def test_cross_origin_blocked():
    r = _client().post("/channels/save", follow_redirects=False, data={
        "channel": "slack", "enabled": "on"})
    assert r.status_code == 403
