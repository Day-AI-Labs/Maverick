"""Fair, two-level concurrency: per-user lanes under a global ceiling.

Proves the guarantee behind "multiple people can run the same fleet at once" —
one principal filling its own lane never blocks another principal's run; only a
host-wide ceiling queues anyone.
"""
from __future__ import annotations

import threading
import time

import pytest
from maverick import runner


@pytest.fixture(autouse=True)
def _reset_lanes(monkeypatch):
    # Small per-user lane for a fast, deterministic test; fresh lane registry.
    monkeypatch.setattr(runner, "MAX_CONCURRENT_GOALS_PER_PRINCIPAL", 2)
    monkeypatch.setattr(runner, "_principal_sems", {})
    yield


def test_principal_semaphore_is_per_principal():
    a1 = runner._principal_semaphore("user:alice")
    a2 = runner._principal_semaphore("user:alice")
    b = runner._principal_semaphore("user:bob")
    assert a1 is a2 and a1 is not b
    # None / anon collapse to one shared lane.
    assert runner._principal_semaphore(None) is runner._principal_semaphore("")


def _stub_run(monkeypatch, *, gate: threading.Event, started: dict):
    """Stub run_goal_in_thread's heavy deps; run_goal_sync blocks on ``gate``."""
    class _Goal:
        status = "done"

    class _World:
        def get_goal(self, gid):
            return _Goal()

        def set_goal_status(self, *a, **k):
            pass

        def close(self):
            pass

    class _Sandbox:
        def close(self):
            pass

    monkeypatch.setattr("maverick.world_model.open_world", lambda *a, **k: _World())
    monkeypatch.setattr("maverick.llm.LLM", lambda *a, **k: object())
    monkeypatch.setattr("maverick.sandbox.build_sandbox", lambda *a, **k: _Sandbox())
    monkeypatch.setattr("maverick.budget.budget_from_config",
                        lambda *a, **k: object())
    monkeypatch.setattr("maverick.trace_pin.pin_trace", lambda *a, **k: None)

    def _blocking_run(llm, world, budget, goal_id, **kw):
        started.setdefault(kw.get("user_id"), []).append(goal_id)
        gate.wait(timeout=5.0)

    monkeypatch.setattr("maverick.orchestrator.run_goal_sync", _blocking_run)


def test_one_user_full_lane_does_not_block_another(monkeypatch):
    gate = threading.Event()
    started: dict = {}
    _stub_run(monkeypatch, gate=gate, started=started)

    def fire(user_id, goal_id):
        threading.Thread(
            target=runner.run_goal_in_thread,
            args=(goal_id,), kwargs={"user_id": user_id}, daemon=True,
        ).start()

    # Alice fills her lane (2) and queues a 3rd that must wait on HER lane.
    fire("user:alice", 1)
    fire("user:alice", 2)
    fire("user:alice", 3)
    # Bob fires once — he must start despite Alice's lane being full.
    fire("user:bob", 99)

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and "user:bob" not in started:
        time.sleep(0.02)

    try:
        assert started.get("user:bob") == [99], "Bob waited behind Alice — not fair"
        # Alice has exactly 2 running; her 3rd is parked on her own lane.
        assert len(started.get("user:alice", [])) == 2
    finally:
        gate.set()  # let every blocked run finish and release its permits
        time.sleep(0.2)
