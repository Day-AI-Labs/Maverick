"""Queue-backed dispatcher: control-plane/data-plane split (ROADMAP spine)."""

from __future__ import annotations

from maverick.capability import Capability
import maverick.queue_dispatcher as qd
import maverick.runner as runner


def test_submit_enqueues_payload_and_returns_none():
    jobs = []
    disp = qd.QueueDispatcher(
        enqueue=lambda name, payload: jobs.append((name, payload))
    )
    out = disp.submit(42, max_dollars=2.0, channel="api", user_id="u1")
    assert out is None  # dispatched, not run inline
    assert len(jobs) == 1
    name, payload = jobs[0]
    assert name == qd.JOB_NAME
    assert payload["goal_id"] == 42
    assert payload["max_dollars"] == 2.0
    assert payload["channel"] == "api"
    assert payload["user_id"] == "u1"
    assert payload["max_depth"] == runner.DEFAULT_MAX_DEPTH  # defaulted


def test_payload_is_json_safe():
    import json

    jobs = []
    qd.QueueDispatcher(lambda n, p: jobs.append(p)).submit(7)
    json.dumps(jobs[0])  # must not raise (no non-serializable objects)


def test_submit_serializes_explicit_capability():
    jobs = []
    cap = Capability(
        principal="user:limited",
        allow_tools=frozenset({"safe_tool"}),
        deny_tools=frozenset({"shell"}),
        max_risk="low",
        expires_at=123.0,
        allow_paths=frozenset({"/tmp/safe/*"}),
        allow_hosts=frozenset({"example.com"}),
    )

    qd.QueueDispatcher(lambda n, p: jobs.append(p)).submit(7, capability=cap)

    assert jobs[0]["capability"] == {
        "principal": "user:limited",
        "allow_tools": ["safe_tool"],
        "deny_tools": ["shell"],
        "max_risk": "low",
        "expires_at": 123.0,
        "allow_paths": ["/tmp/safe/*"],
        "allow_hosts": ["example.com"],
    }


def test_run_queued_goal_restores_explicit_capability(monkeypatch):
    seen = {}

    def fake_run(*, goal_id, **kw):
        seen["goal_id"] = goal_id
        seen.update(kw)
        return "done"

    monkeypatch.setattr(runner, "run_goal_in_thread", fake_run)
    out = qd.run_queued_goal(
        {
            "goal_id": 9,
            "capability": {
                "principal": "user:limited",
                "allow_tools": ["safe_tool"],
                "deny_tools": ["shell"],
                "max_risk": "low",
                "expires_at": 123.0,
                "allow_paths": ["/tmp/safe/*"],
                "allow_hosts": ["example.com"],
            },
        }
    )

    assert out == "done"
    assert seen["capability"] == Capability(
        principal="user:limited",
        allow_tools=frozenset({"safe_tool"}),
        deny_tools=frozenset({"shell"}),
        max_risk="low",
        expires_at=123.0,
        allow_paths=frozenset({"/tmp/safe/*"}),
        allow_hosts=frozenset({"example.com"}),
    )


def test_run_queued_goal_executes_locally(monkeypatch):
    seen = {}

    def fake_run(*, goal_id, **kw):
        seen["goal_id"] = goal_id
        seen.update(kw)
        return "done"

    monkeypatch.setattr(runner, "run_goal_in_thread", fake_run)
    out = qd.run_queued_goal({"goal_id": 9, "max_dollars": 1.5, "channel": "q"})
    assert out == "done"
    assert seen["goal_id"] == 9
    assert seen["max_dollars"] == 1.5
    assert seen["channel"] == "q"


def test_queue_dispatcher_plugs_into_the_runner_seam(monkeypatch):
    jobs = []
    original = runner.get_dispatcher()
    try:
        runner.set_dispatcher(qd.QueueDispatcher(lambda n, p: jobs.append(p)))
        # The public background-dispatch entrypoint now enqueues instead of running.
        assert runner.run_goal_in_background(3, user_id="z") is None
        assert jobs and jobs[0]["goal_id"] == 3
    finally:
        runner.set_dispatcher(original)


def test_install_from_config_noop_without_backend(monkeypatch):
    import maverick.config as cfg

    monkeypatch.setattr(cfg, "load_config", lambda: {})
    original = runner.get_dispatcher()
    try:
        assert qd.install_from_config() is False
        assert runner.get_dispatcher() is original  # unchanged
    finally:
        runner.set_dispatcher(original)
