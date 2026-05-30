"""Council pass: wizard parity with kernel features.

Confirms the eight new wizard steps emit correct TOML, the three new
channel adapters round-trip, and the `_safe_*` helpers replace the
crash-on-bad-input ``int()`` / ``float()`` calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover -- Py 3.10 CI matrix
    import tomli as tomllib  # type: ignore[no-redef]


# ---------- _safe_int / _safe_float ----------

def test_safe_int_handles_whitespace():
    from maverick_installer.wizard import _safe_int
    assert _safe_int("  42 ", default=0) == 42


def test_safe_int_falls_back_on_junk():
    from maverick_installer.wizard import _safe_int
    assert _safe_int("not-a-number", default=9) == 9
    assert _safe_int("", default=5) == 5
    assert _safe_int(None, default=7) == 7  # type: ignore[arg-type]


def test_safe_float_falls_back_on_junk():
    from maverick_installer.wizard import _safe_float
    assert _safe_float("xyz", default=1.5) == 1.5
    assert _safe_float("", default=2.5) == 2.5
    assert _safe_float("3.14", default=0) == 3.14


# ---------- new CHANNELS entries ----------

def test_new_channels_added():
    from maverick_installer.wizard import CHANNELS
    ids = {c[0] for c in CHANNELS}
    assert "bluesky" in ids
    assert "mastodon" in ids
    assert "voice" in ids


def test_bluesky_channel_env_vars():
    from maverick_installer.wizard import CHANNELS
    spec = next(c for c in CHANNELS if c[0] == "bluesky")
    assert "BLUESKY_HANDLE" in spec[2]
    assert "BLUESKY_PASSWORD" in spec[2]


# ---------- new pick_*() functions exist ----------

@pytest.mark.parametrize("name", [
    "pick_web_search",
    "pick_mcp_servers",
    "pick_plugins",
    "pick_tool_acl",
    "pick_rate_limits",
    "pick_retention",
    "pick_persona",
    "pick_notifications",
])
def test_new_pick_exists(name):
    from maverick_installer import wizard
    assert callable(getattr(wizard, name)), f"{name} missing"


# ---------- write_config emits new TOML sections ----------

def _write_full_config(tmp_path: Path, monkeypatch, **overrides) -> dict:
    from maverick_installer import wizard
    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".env")
    base = dict(
        deployment="laptop",
        providers=["anthropic"],
        role_models={},
        channels={},
        safety={"profile": "balanced", "block_threshold": "high",
                "scan_input": True, "scan_tool_calls": True, "scan_output": True},
        budget={"max_dollars": 5.0, "max_wall_seconds": 3600.0, "max_tool_calls": 500},
        sandbox={"backend": "local", "workdir": str(tmp_path / "ws"), "timeout": 60},
        keys={},
        capabilities={"computer_use": False, "browser": False},
    )
    base.update(overrides)
    wizard.write_config(**base)
    body = (tmp_path / "config.toml").read_text()
    return tomllib.loads(body)


def test_write_config_emits_mcp_servers(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        mcp_servers={"fs": {"command": "npx", "args": ["-y", "x"]}},
    )
    assert parsed["mcp_servers"]["fs"]["command"] == "npx"
    assert parsed["mcp_servers"]["fs"]["args"] == ["-y", "x"]


def test_write_config_emits_plugins(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, plugins=["weather", "github-issues"],
    )
    assert parsed["plugins"]["enabled"] == ["weather", "github-issues"]


def test_write_config_roundtrips_backslash_paths_and_allowlist(tmp_path: Path, monkeypatch):
    """A Windows backslash workdir must round-trip (escaped TOML basic string)
    and a channel allowed_user_ids must emit as an ARRAY. Regression: the raw
    f'{k} = "{v}"' emit turned C:\\Users... into an invalid \\U escape (config
    unreadable on Windows) and rendered a list as a quoted string."""
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        sandbox={"backend": "local", "workdir": r"C:\Users\me\maverick ws", "timeout": 60},
        channels={"discord": {
            "enabled": True,
            "bot_token": "${DISCORD_BOT_TOKEN}",
            "allowed_user_ids": ["111", "222"],
        }},
    )
    # Round-trips without TOMLDecodeError and preserves the backslashes.
    assert parsed["sandbox"]["workdir"] == r"C:\Users\me\maverick ws"
    # The allowlist is a TOML array, not a stringified list.
    assert parsed["channels"]["discord"]["allowed_user_ids"] == ["111", "222"]


def test_write_config_emits_tool_acl(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        tool_acl={
            "denied_tools": ["computer"],
            "channels": {"telegram": {"denied_tools": ["shell"]}},
        },
    )
    assert parsed["security"]["denied_tools"] == ["computer"]
    assert parsed["security"]["channels"]["telegram"]["denied_tools"] == ["shell"]


def test_write_config_emits_rate_limits_with_glob(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        rate_limits={"web_search": "10/60", "mcp_*": "60/60"},
    )
    assert parsed["rate_limits"]["web_search"] == "10/60"
    # Glob keys must be quoted in TOML.
    assert parsed["rate_limits"]["mcp_*"] == "60/60"


def test_write_config_emits_retention(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        retention={"audit_days": 90, "episodes_days": 365, "events_days": 180},
    )
    assert parsed["retention"]["audit_days"] == 90
    assert parsed["retention"]["episodes_days"] == 365


def test_write_config_emits_persona(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        persona={"name": "Hawk", "style": "concise"},
    )
    assert parsed["persona"]["name"] == "Hawk"
    assert parsed["persona"]["style"] == "concise"


def test_write_config_emits_notifications(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        notifications={"backend": "ntfy", "topic": "alerts"},
    )
    assert parsed["notifications"]["backend"] == "ntfy"
    assert parsed["notifications"]["topic"] == "alerts"


def test_write_config_emits_web_search_capability(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, web_search_enabled=True,
    )
    assert parsed["capabilities"]["web_search"] is True


def test_write_config_omits_empty_optional_sections(tmp_path: Path, monkeypatch):
    """Unspecified optionals should not emit empty sections."""
    parsed = _write_full_config(tmp_path, monkeypatch)
    for sec in ("mcp_servers", "plugins", "security", "rate_limits",
                "retention", "persona", "notifications"):
        assert sec not in parsed, f"{sec} should be absent"


# ---------- pick_*() functions return safe defaults when declined ----------

class _StubQ:
    """Mock the questionary primitives — every prompt returns 'no'/empty."""

    def __init__(self, monkeypatch):
        monkeypatch.setattr(
            "maverick_installer.wizard._q_confirm",
            lambda *a, **kw: False,
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_text",
            lambda *a, **kw: kw.get("default", ""),
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_select",
            lambda *a, **kw: kw.get("default", a[1][0]) if len(a) > 1 else "",
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_checkbox",
            lambda *a, **kw: kw.get("default", []),
        )


def test_pick_mcp_servers_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_mcp_servers
    assert pick_mcp_servers() == {}


def test_pick_plugins_returns_empty_when_no_entry_points(monkeypatch):
    _StubQ(monkeypatch)
    # Force empty entry_points discovery.
    import maverick_installer.wizard as w
    real_plugins = sys.modules.get("maverick.plugins")
    try:
        # Remove module so the import in pick_plugins re-imports / fails.
        sys.modules.pop("maverick.plugins", None)
        out = w.pick_plugins()
        assert out == []
    finally:
        if real_plugins:
            sys.modules["maverick.plugins"] = real_plugins


def test_pick_tool_acl_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_tool_acl
    assert pick_tool_acl(channels={}) == {}


def test_pick_rate_limits_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_rate_limits
    assert pick_rate_limits(channels={}) == {}


def test_pick_retention_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_retention
    assert pick_retention() == {}


def test_pick_persona_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_persona
    assert pick_persona() == {}


def test_pick_notifications_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_notifications
    cfg, envs = pick_notifications()
    assert cfg == {}
    assert envs == []


def test_pick_web_search_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_web_search
    enabled, envs = pick_web_search()
    assert enabled is False
    assert envs == []
