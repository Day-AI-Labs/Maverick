"""gRPC goal service (transport-agnostic; no grpc required)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from maverick.grpc_api.service import EventDTO, GoalService


@dataclass
class _Goal:
    id: int
    status: str = "pending"
    result: str | None = None
    owner: str = ""


@dataclass
class _Event:
    id: int
    goal_id: int
    agent: str
    kind: str
    content: str
    ts: float


class _FakeWorld:
    """In-memory stand-in for WorldModel covering the service's surface."""

    def __init__(self, shared: dict):
        self.s = shared  # shared across the fresh-per-call instances

    def create_goal(self, title, description="", *, owner=""):
        self.s["seq"] += 1
        gid = self.s["seq"]
        self.s["goals"][gid] = _Goal(id=gid, owner=owner)
        self.s["titles"][gid] = title
        return gid

    def get_goal(self, goal_id):
        return self.s["goals"].get(goal_id)

    def set_goal_status(self, goal_id, status, *, result=None):
        g = self.s["goals"].get(goal_id)
        if g:
            g.status = status
            g.result = result

    def goal_events(self, goal_id, since_id=0, limit=200):
        return [e for e in self.s["events"] if e.goal_id == goal_id and e.id > since_id]

    def close(self):
        self.s["closes"] += 1


def _shared():
    return {"seq": 0, "goals": {}, "titles": {}, "events": [], "closes": 0}


def _service(shared, **kw):
    return GoalService(
        world_factory=lambda: _FakeWorld(shared),
        dispatch=lambda gid, **k: shared.setdefault("dispatched", []).append((gid, k)),
        spawn=lambda fn: fn(),  # run inline
        sleep=lambda _s: None,
        **kw,
    )


def test_start_goal_creates_and_dispatches():
    shared = _shared()
    svc = _service(shared)
    gid = svc.start_goal("Do the thing", "details", max_dollars=2.0, user_id="u1")
    assert gid == 1
    assert shared["titles"][1] == "Do the thing"
    assert shared["dispatched"] == [
        (1, {
            "max_dollars": 2.0,
            "max_wall_seconds": None,
            "channel": None,
            "user_id": "u1",
            "capability": None,
        })
    ]
    assert shared["closes"] >= 1  # world closed after create


def test_start_goal_rejects_blank_title():
    svc = _service(_shared())
    with pytest.raises(ValueError):
        svc.start_goal("   ")


def test_stream_episode_yields_events_then_terminal_status():
    shared = _shared()
    shared["goals"][7] = _Goal(id=7, status="active")
    shared["events"] = [
        _Event(1, 7, "orchestrator", "plan", "step one", 1.0),
        _Event(2, 7, "coder", "tool", "ran tests", 2.0),
    ]

    # After the service reads events once, flip the goal terminal so the loop ends.
    calls = {"n": 0}
    orig = _FakeWorld.get_goal

    def get_goal(self, goal_id):
        calls["n"] += 1
        if calls["n"] >= 1:
            self.s["goals"][7].status = "done"
            self.s["goals"][7].result = "ok"
        return orig(self, goal_id)

    svc = _service(shared)
    # Patch get_goal on the fake to terminate after first poll.
    _FakeWorld.get_goal = get_goal
    try:
        out = list(svc.stream_episode(7))
    finally:
        _FakeWorld.get_goal = orig

    kinds = [e.kind for e in out]
    assert kinds == ["plan", "tool", "status"]
    assert isinstance(out[-1], EventDTO)
    assert out[-1].content == "done"  # terminal status carried as final event
    assert shared["closes"] >= 1


def test_stream_episode_drains_backlog_past_one_page_before_terminal():
    # Regression: a terminal goal with >200 pending events must not drop the
    # tail. goal_events here honours the LIMIT (like the real world model), so a
    # naive single-read would stream only the first 200 and emit the synthetic
    # status, stranding events 201..N.
    shared = _shared()
    shared["goals"][7] = _Goal(id=7, status="done", result="ok")
    shared["events"] = [
        _Event(i, 7, "worker", "tool", f"step {i}", float(i))
        for i in range(1, 251)
    ]

    class _PagedWorld(_FakeWorld):
        def goal_events(self, goal_id, since_id=0, limit=200):
            rows = [
                e for e in self.s["events"]
                if e.goal_id == goal_id and e.id > since_id
            ]
            return rows[:limit]

    svc = GoalService(
        world_factory=lambda: _PagedWorld(shared),
        dispatch=lambda gid, **k: None,
        spawn=lambda fn: fn(),
        sleep=lambda _s: None,
    )
    out = list(svc.stream_episode(7))

    tool_events = [e for e in out if e.kind == "tool"]
    assert len(tool_events) == 250  # all backlog drained, none dropped
    assert [e.id for e in tool_events] == list(range(1, 251))
    assert out[-1].kind == "status" and out[-1].content == "done"


def test_stream_episode_stops_on_missing_goal():
    shared = _shared()  # goal 99 never created
    svc = _service(shared)
    assert list(svc.stream_episode(99)) == []


def test_cancel_marks_cancellable_goal():
    shared = _shared()
    shared["goals"][3] = _Goal(id=3, status="active")
    svc = _service(shared)
    assert svc.cancel(3) is True
    assert shared["goals"][3].status == "cancelled"


def test_cancel_noop_on_terminal_or_missing():
    shared = _shared()
    shared["goals"][4] = _Goal(id=4, status="done")
    svc = _service(shared)
    assert svc.cancel(4) is False  # already terminal
    assert svc.cancel(123) is False  # missing


def test_status_reports_goal():
    shared = _shared()
    shared["goals"][5] = _Goal(id=5, status="active", result=None)
    svc = _service(shared)
    st = svc.status(5)
    assert st is not None and st.status == "active"
    assert svc.status(404) is None
