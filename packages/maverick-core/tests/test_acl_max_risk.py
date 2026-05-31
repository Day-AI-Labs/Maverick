"""Per-identity max-risk ceiling for tool ACLs.

A ``max_risk`` config key (global / per-channel / per-user) caps the risk
level a context may reach. Default: no ceiling, so behaviour matches the
existing per-user tool subset unless configured.
"""
from __future__ import annotations

import importlib


def _write_config(tmp_path, body: str) -> None:
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.toml").write_text(body)
    import maverick.config as cfg_mod
    importlib.reload(cfg_mod)


class _FakeSandbox:
    workdir = "."


class _FakeWorld:
    pass


# ---------- risk classification ----------

def test_tool_risk_defaults():
    from maverick.safety.tool_risk import tool_risk
    assert tool_risk("shell") == "high"
    assert tool_risk("read_file") == "low"
    # Unclassified tool falls back to medium.
    assert tool_risk("some_unknown_tool") == "medium"


def test_tool_risk_config_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security.tool_risk]
read_file = "high"
"mcp_*" = "high"
''')
    from maverick.safety.tool_risk import tool_risk
    assert tool_risk("read_file") == "high"            # exact override
    assert tool_risk("mcp_github__list") == "high"     # glob override


# ---------- resolve_max_risk: most restrictive wins ----------

def test_resolve_max_risk_unset_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '[security]\ndenied_tools = ["computer"]\n')
    from maverick.safety.tool_acl import resolve_max_risk
    assert resolve_max_risk(user_id="tg:1") is None


def test_resolve_max_risk_tightest_layer_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security]
max_risk = "high"

[security.users."tg:42"]
max_risk = "low"
''')
    from maverick.safety.tool_acl import resolve_max_risk
    # Global high + user low -> low (most restrictive).
    assert resolve_max_risk(user_id="tg:42") == "low"
    # Without the user, only the global high applies.
    assert resolve_max_risk() == "high"


# ---------- apply_to_registry: ceiling drops high-risk tools ----------

def test_user_low_ceiling_drops_high_risk_tool(tmp_path, monkeypatch):
    """A user with max_risk=low cannot resolve a high-risk tool (shell)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security.users."tg:42"]
max_risk = "low"
''')
    from maverick.tools import base_registry
    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    assert "shell" in {t.name for t in reg.all()}

    from maverick.safety.tool_acl import apply_to_registry
    apply_to_registry(reg, user_id="tg:42")
    names = {t.name for t in reg.all()}
    assert "shell" not in names         # high-risk dropped
    assert "write_file" not in names    # high-risk dropped
    assert "read_file" in names         # low-risk kept


def test_user_high_ceiling_keeps_high_risk_tool(tmp_path, monkeypatch):
    """max_risk=high (or unset) keeps current behaviour -- shell stays."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security.users."tg:42"]
max_risk = "high"
''')
    from maverick.tools import base_registry
    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())

    from maverick.safety.tool_acl import apply_to_registry
    apply_to_registry(reg, user_id="tg:42")
    names = {t.name for t in reg.all()}
    assert "shell" in names
    assert "read_file" in names


def test_no_ceiling_keeps_high_risk_tool(tmp_path, monkeypatch):
    """No max_risk anywhere -> no cap; shell is resolvable."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '[security]\ndenied_tools = ["computer"]\n')
    from maverick.tools import base_registry
    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())

    from maverick.safety.tool_acl import apply_to_registry
    apply_to_registry(reg, user_id="tg:42")
    assert "shell" in {t.name for t in reg.all()}
