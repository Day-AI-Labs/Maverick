"""Goal-execution dispatcher seam (threads now, queue later).

``run_goal_in_background`` routes through a swappable Dispatcher so a future
queue/worker backend is a ``set_dispatcher`` call, not a caller rewrite.
"""
from __future__ import annotations

import maverick.runner as runner


def test_default_dispatcher_is_local_thread():
    assert isinstance(runner.get_dispatcher(), runner.LocalThreadDispatcher)


def test_run_goal_in_background_delegates_to_active_dispatcher(monkeypatch):
    calls = []

    class FakeDispatcher:
        def submit(self, goal_id, **kw):
            calls.append((goal_id, kw))
            return "done"

    monkeypatch.setattr(runner, "_dispatcher", FakeDispatcher())
    out = runner.run_goal_in_background(
        7, max_dollars=2.0, channel="api", user_id="u1",
    )
    assert out == "done"
    assert calls[0][0] == 7
    assert calls[0][1]["max_dollars"] == 2.0
    assert calls[0][1]["channel"] == "api"
    assert calls[0][1]["user_id"] == "u1"


def test_local_dispatcher_delegates_to_run_goal_in_thread(monkeypatch):
    seen = {}

    def fake_run(*, goal_id, **kw):
        seen["goal_id"] = goal_id
        seen.update(kw)
        return "blocked"

    monkeypatch.setattr(runner, "run_goal_in_thread", fake_run)
    out = runner.LocalThreadDispatcher().submit(42, max_wall_seconds=30.0)
    assert out == "blocked"
    assert seen["goal_id"] == 42
    assert seen["max_wall_seconds"] == 30.0


def test_set_dispatcher_swaps_and_is_restorable():
    original = runner.get_dispatcher()
    try:
        sentinel = runner.LocalThreadDispatcher()
        runner.set_dispatcher(sentinel)
        assert runner.get_dispatcher() is sentinel
    finally:
        runner.set_dispatcher(original)
    assert runner.get_dispatcher() is original
