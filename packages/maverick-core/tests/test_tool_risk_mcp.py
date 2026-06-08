"""MCP tools fail safe to ``high`` risk by default.

An unclassified ``mcp_*`` tool runs arbitrary code through a third-party
server, so -- unlike a generic unclassified tool, which stays ``medium`` --
it defaults to ``high``. A ``[security.tool_risk]`` override is still checked
first, so a trusted MCP server can be relaxed deliberately. This closes the
gap where a `max_risk="medium"` ceiling / governance gate silently admitted
arbitrary MCP tools.
"""
from __future__ import annotations

import importlib


def _write_config(tmp_path, body: str = "") -> None:
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.toml").write_text(body)
    import maverick.config as cfg_mod
    importlib.reload(cfg_mod)


def test_unclassified_mcp_tool_defaults_high(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)  # no overrides
    from maverick.safety.tool_risk import tool_risk
    assert tool_risk("mcp_github__create_issue") == "high"
    assert tool_risk("mcp_anything__do") == "high"


def test_non_mcp_unknown_stays_medium(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)
    from maverick.safety.tool_risk import tool_risk
    # The generic fallback is unchanged; only the `mcp_` *prefix* triggers the
    # high default (a name that merely contains "mcp" does not).
    assert tool_risk("some_unknown_tool") == "medium"
    assert tool_risk("not_mcp_really") == "medium"


def test_builtin_classifications_unaffected(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)
    from maverick.safety.tool_risk import tool_risk
    assert tool_risk("shell") == "high"
    assert tool_risk("read_file") == "low"


def test_config_override_relaxes_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '\n'.join([
        "[security.tool_risk]",
        '"mcp_*" = "medium"',
        '"mcp_trusted__read" = "low"',
    ]))
    from maverick.safety.tool_risk import tool_risk
    assert tool_risk("mcp_other__write") == "medium"   # glob relaxation wins
    assert tool_risk("mcp_trusted__read") == "low"     # exact override wins


def test_mcp_dropped_under_medium_ceiling_by_default(tmp_path, monkeypatch):
    # End-to-end: with a max_risk=medium ceiling and NO mcp override, an mcp
    # tool now exceeds the ceiling (high) and is flagged for dropping -- the
    # whole point of the fail-safe default.
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)
    from maverick.safety.tool_risk import tools_exceeding
    over = tools_exceeding(["mcp_evil__shell", "read_file"], "medium")
    assert over == {"mcp_evil__shell"}


def test_sensitive_enterprise_connectors_default_high(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path)
    from maverick.safety.tool_risk import tool_risk, tools_exceeding

    connectors = ["sugarcrm", "paychex", "opsgenie"]
    assert {name: tool_risk(name) for name in connectors} == {
        "sugarcrm": "high",
        "paychex": "high",
        "opsgenie": "high",
    }
    assert tools_exceeding(connectors, "medium") == set(connectors)
