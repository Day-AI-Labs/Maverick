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
