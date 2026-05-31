"""Bounded-growth / DoS-hardening regressions from the red-team audit:
the blackboard and the A2A in-memory task store must not grow without limit,
and runtime-override tool names are re-validated on read.
"""
from __future__ import annotations

import asyncio


def test_blackboard_caps_entries(monkeypatch):
    from maverick.blackboard import Blackboard
    monkeypatch.setattr(Blackboard, "_MAX_ENTRIES", 5)
    b = Blackboard()
    for i in range(20):
        b.post("agent", "observation", f"entry-{i}")
    assert len(b.entries) == 5
    # The most recent entries are the ones retained.
    assert b.entries[-1].content == "entry-19"
    assert b.entries[0].content == "entry-15"


def test_a2a_task_store_is_bounded(monkeypatch):
    import maverick.a2a_tasks as a2a
    monkeypatch.setattr(a2a, "_MAX_TASKS", 3)

    def _runner(text, *, max_dollars, max_wall, max_depth):
        return "ok"

    eng = a2a.TaskEngine(runner=_runner)
    ids = []
    for i in range(10):
        t = asyncio.run(eng.send(
            {"message": {"role": "user", "parts": [{"kind": "text", "text": f"g{i}"}]}}
        ))
        ids.append(t["id"])
    assert len(eng._tasks) == 3  # capped
    # The oldest were evicted; the newest survive.
    assert ids[-1] in eng._tasks
    assert ids[0] not in eng._tasks


def test_runtime_overrides_revalidates_names(tmp_path, monkeypatch):
    import maverick.runtime_overrides as ro
    override = tmp_path / "runtime-overrides.toml"
    override.write_text(
        '[security]\n'
        'denied_tools = ["shell", "BAD NAME", "../escape", "ok_tool"]\n'
    )
    monkeypatch.setattr(ro, "OVERRIDES_PATH", override)
    ro._announced.clear()
    denied = ro.denied_tools()
    # Valid names kept; junk ("BAD NAME", "../escape") dropped.
    assert denied == {"shell", "ok_tool"}
