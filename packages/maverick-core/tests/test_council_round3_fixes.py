"""Regression tests for adversarial-council round-3 (clean) fixes."""
from __future__ import annotations

import asyncio


def _boom(args):
    raise RuntimeError("kaboom")


# --- ops HIGH: ToolRegistry must emit the tool_calls metric (was never wired) ---

def test_tool_registry_emits_tool_metric(monkeypatch):
    import maverick.observability as obs
    from maverick.tools import Tool, ToolRegistry

    calls: list = []
    monkeypatch.setattr(
        obs, "record_metric",
        lambda name, *a, **k: calls.append((name, k.get("labels"))),
    )
    reg = ToolRegistry()
    reg.register(Tool(name="echo", description="e",
                      input_schema={"type": "object", "properties": {}},
                      fn=lambda args: "ok"))
    reg.register(Tool(name="boom", description="b",
                      input_schema={"type": "object", "properties": {}},
                      fn=_boom))
    asyncio.run(reg.run("echo", {}))
    asyncio.run(reg.run("boom", {}))
    assert ("tool_calls", {"tool": "echo", "status": "ok"}) in calls
    assert ("tool_calls", {"tool": "boom", "status": "error"}) in calls


# --- privacy: `maverick erase` must append an audit event (hashed subject) ---

def test_erase_emits_hashed_audit_event(tmp_path, monkeypatch):
    import hashlib
    import os

    os.environ.pop("MAVERICK_DB", None)
    from click.testing import CliRunner

    import maverick.audit as audit_mod
    from maverick import cli as cli_mod
    from maverick.world_model import WorldModel

    captured: list = []
    monkeypatch.setattr(
        audit_mod, "record",
        lambda kind, **payload: captured.append((kind, payload)),
    )

    db = tmp_path / "world.db"
    wm = WorldModel(db)
    conv_id = wm.get_or_create_conversation("telegram", "u123").id
    gid = wm.create_goal("hello")
    wm.append_turn(conv_id, "user", "hi there", goal_id=gid)
    wm.close()

    result = CliRunner().invoke(
        cli_mod.main,
        ["--db", str(db), "erase", "--channel", "telegram",
         "--user", "u123", "--yes"],
    )
    assert result.exit_code == 0, result.output

    erase_events = [p for (k, p) in captured if k == "erase"]
    assert erase_events, "no erase audit event emitted"
    ev = erase_events[0]
    assert ev["channel"] == "telegram"
    # Subject is hashed, never stored in plaintext (Art. 30 without re-leaking).
    assert "u123" not in str(ev)
    assert ev["user_hash"] == hashlib.sha256(b"u123").hexdigest()[:16]
