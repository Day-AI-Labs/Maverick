"""Dashboard-owned runtime tool-deny overlay + ACL union."""
from __future__ import annotations

import stat
from pathlib import Path


def _point_overlay(monkeypatch, tmp_path: Path):
    from maverick import runtime_overrides
    monkeypatch.setattr(runtime_overrides, "OVERRIDES_PATH", tmp_path / "runtime-overrides.toml")
    return runtime_overrides


def test_denied_tools_empty_when_no_file(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    assert ro.denied_tools() == set()


def test_disable_then_denied(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.disable_tool("shell")
    assert ro.denied_tools() == {"shell"}
    ro.disable_tool("browser")
    assert ro.denied_tools() == {"shell", "browser"}


def test_enable_removes(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.disable_tool("shell")
    ro.disable_tool("browser")
    ro.enable_tool("shell")
    assert ro.denied_tools() == {"browser"}


def test_enable_unknown_is_noop(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.disable_tool("shell")
    ro.enable_tool("never-added")  # no raise
    assert ro.denied_tools() == {"shell"}


def test_overlay_written_at_0600(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.disable_tool("shell")
    path = tmp_path / "runtime-overrides.toml"
    assert path.exists()
    import os
    if os.name != "nt":  # NTFS reports 0o666 regardless of chmod
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_overlay_is_valid_toml(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.disable_tool("shell")
    ro.disable_tool("computer")
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    parsed = tomllib.loads((tmp_path / "runtime-overrides.toml").read_text())
    assert set(parsed["security"]["denied_tools"]) == {"shell", "computer"}


def test_corrupt_overlay_degrades_to_empty(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    (tmp_path / "runtime-overrides.toml").write_text("this is not { valid toml")
    assert ro.denied_tools() == set()


def test_disable_rejects_invalid_tool_name(monkeypatch, tmp_path):
    ro = _point_overlay(monkeypatch, tmp_path)
    try:
        ro.disable_tool('bad"name')
        raise AssertionError("expected ValueError for invalid tool name")
    except ValueError:
        pass


# ---------- ACL union ----------

def test_acl_unions_overlay_into_deny(monkeypatch, tmp_path):
    """resolve_lists must add the overlay's denied tools to the deny-set."""
    from maverick import runtime_overrides
    from maverick.safety import tool_acl
    monkeypatch.setattr(runtime_overrides, "OVERRIDES_PATH", tmp_path / "ro.toml")
    # No config ACL; empty config path.
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "config.toml"))
    runtime_overrides.disable_tool("shell")
    allowed, denied = tool_acl.resolve_lists()
    assert "shell" in denied


def test_acl_overlay_filters_registry(monkeypatch, tmp_path):
    """End-to-end: a disabled tool is actually dropped from the registry."""
    from maverick import runtime_overrides
    monkeypatch.setattr(runtime_overrides, "OVERRIDES_PATH", tmp_path / "ro.toml")
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "config.toml"))
    runtime_overrides.disable_tool("shell")

    from unittest.mock import MagicMock

    from maverick.tools import base_registry
    reg = base_registry(world=MagicMock(), sandbox=MagicMock(__class__=type("Local", (), {})))
    names = {t.name for t in reg.all()}
    assert "shell" not in names, "overlay-denied tool still in registry"


def test_concurrent_disables_do_not_lose_tools(monkeypatch, tmp_path):
    """Every mutator re-reads the whole overlay and rewrites it; without
    serialization two concurrent writes lose one change. N concurrent
    disable_tool calls must all land on the deny-list (a dropped denied_tools
    update would silently re-enable a tool the operator just disabled)."""
    import threading

    ro = _point_overlay(monkeypatch, tmp_path)
    names = [f"tool{i:02d}" for i in range(24)]

    def disable(n: str):
        ro.disable_tool(n)

    threads = [threading.Thread(target=disable, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert ro.denied_tools() == set(names)
    # No fixed-temp droppings from concurrent writers.
    assert list(tmp_path.glob("*.tmp")) == []


def test_disable_racing_set_budget_keeps_both(monkeypatch, tmp_path):
    """A disable_tool racing a set_budget (a DIFFERENT surface in the same
    file) must not have either change clobbered by a stale re-read."""
    import threading

    ro = _point_overlay(monkeypatch, tmp_path)
    barrier = threading.Barrier(2)

    def do_disable():
        barrier.wait()
        ro.disable_tool("shell")

    def do_budget():
        barrier.wait()
        ro.set_budget(12.5)

    ts = [threading.Thread(target=do_disable), threading.Thread(target=do_budget)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert ro.denied_tools() == {"shell"}
    assert ro.budget_override() == 12.5
