"""Q1 2026 batch 2: consent, tool_acl, budget_status, plugin_manifest, webhooks."""
from __future__ import annotations

import pytest

# ---------- consent ----------

def test_consent_auto_approve_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    from maverick.safety.consent import require_consent
    d = require_consent("test-action", risk="high")
    assert d.granted is True
    assert d.source == "auto"


def test_consent_auto_deny_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    from maverick.safety.consent import require_consent
    d = require_consent("test-action")
    assert d.granted is False
    assert d.source == "auto"


def test_consent_ask_mode_non_tty_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # 'ask' mode in a non-tty context (pytest captures stdin) denies.
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "ask")
    from maverick.safety.consent import require_consent
    d = require_consent("test-action")
    assert d.granted is False
    assert d.source == "non-tty-deny"


def test_consent_default_is_opt_in_auto_approve(tmp_path, monkeypatch):
    # With no MAVERICK_CONSENT_MODE set, gating is OFF (auto-approve) so wiring
    # require_consent into tools doesn't change out-of-the-box behavior.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    from maverick.safety.consent import require_consent
    d = require_consent("test-action")
    assert d.granted is True
    assert d.source == "auto"


def test_consent_raise_on_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    from maverick.safety.consent import ConsentDenied, require_consent
    with pytest.raises(ConsentDenied):
        require_consent("rm-rf", raise_on_deny=True)


def test_consent_ledger_grant_then_check(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    from maverick.safety.consent import grant_persistent, list_grants, require_consent
    grant_persistent("force-push", scope="main")
    grants = list_grants()
    assert ("force-push", "main") in grants
    d = require_consent("force-push", scope="main")
    assert d.granted is True
    assert d.source == "ledger"


def test_consent_revoke(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.safety.consent import grant_persistent, list_grants, revoke
    grant_persistent("rm-rf", scope="/tmp/test")
    assert ("rm-rf", "/tmp/test") in list_grants()
    assert revoke("rm-rf", scope="/tmp/test") is True
    assert ("rm-rf", "/tmp/test") not in list_grants()
    # Idempotent: revoking again returns False.
    assert revoke("rm-rf", scope="/tmp/test") is False


# ---------- tool_acl ----------

def test_tool_acl_no_lists_keeps_all():
    from maverick.safety.tool_acl import filter_tools
    out = filter_tools({"a", "b", "c"}, allowed=set(), denied=set())
    assert out == {"a", "b", "c"}


def test_tool_acl_allow_list_filters():
    from maverick.safety.tool_acl import filter_tools
    out = filter_tools({"a", "b", "c"}, allowed={"a", "b"})
    assert out == {"a", "b"}


def test_tool_acl_deny_list_drops():
    from maverick.safety.tool_acl import filter_tools
    out = filter_tools({"a", "b", "c"}, denied={"b"})
    assert out == {"a", "c"}


def test_tool_acl_allow_then_deny():
    """When both lists set, allow filters first, then deny drops further."""
    from maverick.safety.tool_acl import filter_tools
    out = filter_tools({"a", "b", "c", "d"}, allowed={"a", "b", "c"}, denied={"b"})
    assert out == {"a", "c"}


def test_tool_acl_apply_to_registry(tmp_path, monkeypatch):
    """apply_to_registry mutates the registry in place per config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Write a config with denied_tools.
    config_dir = tmp_path / ".maverick"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[security]\ndenied_tools = ["computer", "browser"]\n'
    )
    # Force reload of the cached default config path.
    import importlib

    import maverick.config as cfg_mod
    importlib.reload(cfg_mod)

    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    # Include the optional tools so we can verify they get dropped.
    reg = base_registry(
        world=_FakeWorld(), sandbox=_FakeSandbox(),
        enable_computer_use=True, enable_browser=True,
    )
    names = {t.name for t in reg.all()}
    assert "computer" not in names
    assert "browser" not in names
    # Core tools survived.
    assert "shell" in names


def test_tool_acl_blocks_late_registered_tools(tmp_path, monkeypatch):
    """ACL should also apply to tools registered after apply_to_registry."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".maverick"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[security]\nallowed_tools = ["read_file"]\n'
    )
    import importlib

    import maverick.config as cfg_mod
    importlib.reload(cfg_mod)

    from maverick.tools import Tool, base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    reg.register(Tool(name="late_tool", description="x", input_schema={}, fn=lambda _a: "ok"))
    names = {t.name for t in reg.all()}
    assert "read_file" in names
    assert "late_tool" not in names


# ---------- budget_status ----------

def test_budget_status_no_budget():
    from maverick.tools.budget_status import budget_status
    tool = budget_status(budget=None)
    out = tool.fn({})
    assert "no Budget bound" in out


def test_budget_status_with_budget():
    from maverick.budget import Budget
    from maverick.tools.budget_status import budget_status
    b = Budget(max_dollars=10.0)
    b.record_tokens(1000, 500, model="claude-opus-4-7")
    tool = budget_status(budget=b)
    out = tool.fn({})
    assert "dollars:" in out
    assert "input tokens" in out
    assert "output tokens" in out
    assert "tool calls:" in out
    # Cost recorded -> not zero.
    assert "$0.0000" not in out


def test_budget_status_warns_at_90pct():
    from maverick.budget import Budget
    from maverick.tools.budget_status import budget_status
    b = Budget(max_dollars=1.0)
    # Use atomic update to push spend high without tripping check().
    with b._lock:
        b.dollars = 0.95
    out = budget_status(budget=b).fn({})
    assert "WARNING" in out


# ---------- plugin_manifest ----------

def test_plugin_manifest_parse_minimal_valid():
    from maverick.plugin_manifest import MAVERICK_API_VERSION, parse_dict
    m = parse_dict({
        "plugin": {
            "name": "x",
            "version": "0.1.0",
            "api_version": MAVERICK_API_VERSION,
        }
    })
    assert m is not None
    assert m.name == "x"
    assert m.is_compatible()


def test_plugin_manifest_missing_required_field():
    from maverick.plugin_manifest import parse_dict
    m = parse_dict({"plugin": {"name": "x", "version": "0.1.0"}})  # no api_version
    assert m is None


def test_plugin_manifest_incompatible_version_warns():
    from maverick.plugin_manifest import parse_dict
    m = parse_dict({
        "plugin": {
            "name": "x", "version": "0.1.0",
            "api_version": "999",
        }
    })
    assert m is not None
    assert not m.is_compatible()
    assert any("api_version" in w for w in m.warnings)


@pytest.mark.parametrize("api_version", ["1", "1.0", "01", "1.5"])
def test_plugin_manifest_compatible_by_major(api_version):
    # Kernel major is 1; any plugin with major 1 is compatible regardless
    # of how its api_version string is spelled.
    from maverick.plugin_manifest import parse_dict
    m = parse_dict({
        "plugin": {"name": "x", "version": "0.1.0", "api_version": api_version}
    })
    assert m is not None
    assert m.is_compatible()
    assert not any("api_version" in w for w in m.warnings)


@pytest.mark.parametrize("api_version", ["2", "0", "abc", "v1"])
def test_plugin_manifest_incompatible_by_major(api_version):
    from maverick.plugin_manifest import parse_dict
    m = parse_dict({
        "plugin": {"name": "x", "version": "0.1.0", "api_version": api_version}
    })
    assert m is not None
    assert not m.is_compatible()
    assert any("api_version" in w for w in m.warnings)


def test_plugin_manifest_loads_capabilities_permissions():
    from maverick.plugin_manifest import MAVERICK_API_VERSION, parse_dict
    m = parse_dict({
        "plugin": {
            "name": "x", "version": "0.1.0",
            "api_version": MAVERICK_API_VERSION,
            "capabilities": {
                "tools": ["my_tool", "other"],
                "channels": ["telegram"],
            },
            "permissions": {
                "network": True, "fs_write": False,
                "sensitive_envs": ["MY_API_KEY"],
            },
        }
    })
    assert m is not None
    assert m.capabilities.tools == ["my_tool", "other"]
    assert m.capabilities.channels == ["telegram"]
    assert m.permissions.network is True
    assert m.permissions.fs_write is False
    assert m.permissions.sensitive_envs == ["MY_API_KEY"]


def test_plugin_manifest_parse_file(tmp_path):
    from maverick.plugin_manifest import MAVERICK_API_VERSION, parse
    f = tmp_path / "maverick-plugin.toml"
    f.write_text(
        f'[plugin]\nname = "x"\nversion = "0.1.0"\n'
        f'api_version = "{MAVERICK_API_VERSION}"\n'
    )
    m = parse(f)
    assert m is not None
    assert m.name == "x"


def test_plugin_manifest_parse_missing_file(tmp_path):
    from maverick.plugin_manifest import parse
    assert parse(tmp_path / "nope.toml") is None


# ---------- webhooks ----------

def test_webhooks_no_urls_no_op():
    from maverick.webhooks import fire
    # Pass empty urls explicitly to bypass config lookup.
    n = fire("test_event", {"x": 1}, urls=[], secret=None)
    assert n == 0


def test_webhooks_signature_round_trip():
    """verify_signature accepts the signature fire() would produce."""
    from maverick.webhooks import _sign, verify_signature
    body = b'{"hello": "world"}'
    sig = _sign(body, "secret-key")
    assert sig.startswith("sha256=")
    assert verify_signature(body, sig, "secret-key") is True
    assert verify_signature(body, sig, "wrong-key") is False
    assert verify_signature(body, "garbage", "secret-key") is False


def test_webhooks_fires_per_url(monkeypatch):
    """fire() submits one POST per URL configured."""
    from maverick import webhooks
    posted: list[str] = []

    def _fake_post(url, body, headers, timeout):
        posted.append(url)

    monkeypatch.setattr(webhooks, "_post", _fake_post)
    # Wait for threadpool to drain by submitting then joining.
    n = webhooks.fire(
        "goal_finished",
        {"goal_id": 1, "status": "succeeded"},
        urls=["https://a.example", "https://b.example"],
        secret=None,
    )
    # Drain the pool.
    exec_ = webhooks._get_executor()
    exec_.shutdown(wait=True)
    # Reset for downstream tests so they get a fresh pool.
    webhooks._executor = None
    assert n == 2
    assert sorted(posted) == ["https://a.example", "https://b.example"]


def test_webhooks_timestamped_signature_replay_window():
    """A timestamped signature is rejected once the timestamp falls outside the
    max-age window (replay defence) but accepted while fresh."""
    import time

    from maverick.webhooks import _sign, verify_signature
    body = b'{"event": "x"}'
    fresh = str(int(time.time()))
    sig = _sign(body, "k", timestamp=fresh)
    # fresh -> accepted
    assert verify_signature(body, sig, "k", timestamp=fresh, max_age=300) is True
    # stale -> rejected even though the HMAC matches the (stale) timestamp
    stale = str(int(time.time()) - 10_000)
    stale_sig = _sign(body, "k", timestamp=stale)
    assert verify_signature(body, stale_sig, "k", timestamp=stale, max_age=300) is False
    # a captured fresh signature replayed with a tampered timestamp -> rejected
    assert verify_signature(body, sig, "k", timestamp=stale, max_age=300) is False


def test_webhooks_outbound_post_blocks_ssrf(monkeypatch):
    """_post routes through the SSRF guard: a loopback/metadata target makes no
    outbound request."""
    import httpx
    from maverick import webhooks
    posted: list[str] = []

    def _spy(self, url, **kw):  # pragma: no cover - must not run for blocked host
        posted.append(str(url))

        class _R:
            status_code = 200
            text = ""

        return _R()

    monkeypatch.setattr(httpx.Client, "post", _spy)
    for url in (
        "http://127.0.0.1:8765/internal",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ):
        webhooks._post(url, b"{}", {}, 5.0)
    assert posted == []


def test_webhooks_outbound_post_allows_public(monkeypatch):
    """A public outbound target still fires through the guard."""
    import httpx
    from maverick import webhooks
    posted: list[str] = []

    def _spy(self, url, **kw):
        posted.append(str(url))

        class _R:
            status_code = 200
            text = ""

        return _R()

    monkeypatch.setattr(httpx.Client, "post", _spy)
    # Literal public IP -> deterministic offline (no DNS).
    webhooks._post("http://93.184.216.34/wh", b"{}", {}, 5.0)
    assert posted == ["http://93.184.216.34/wh"]
