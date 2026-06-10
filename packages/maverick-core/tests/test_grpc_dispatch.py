"""gRPC dispatch: the RunGoal service half, the GrpcDispatcher client half
(fake stub), config installation, and queue-wins precedence."""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
from maverick.capability import Capability
from maverick.grpc_api.service import GoalService
from maverick.grpc_dispatcher import GrpcDispatcher, configured_target, install_from_config


class _FakeWorld:
    def __init__(self, goals):
        self._goals = goals

    def get_goal(self, gid):
        return self._goals.get(gid)

    def close(self):
        pass


def _goal(status="done", result="all good"):
    return types.SimpleNamespace(status=status, result=result)


# ---- service half: RunGoal ----

def test_run_goal_dispatches_existing_and_returns_terminal():
    goals = {7: _goal(status="running")}
    calls = []

    def dispatch(goal_id, **kw):
        calls.append((goal_id, kw))
        goals[7] = _goal(status="done", result="finished")

    svc = GoalService(world_factory=lambda: _FakeWorld(goals), dispatch=dispatch)
    cap = Capability(principal="user:w1", deny_tools=frozenset({"shell"}))
    st = svc.run_goal(
        7, max_dollars=2.5, channel="grpc", user_id="w1",
        max_depth=1, capability=cap,
    )
    assert calls and calls[0][0] == 7
    assert calls[0][1]["max_dollars"] == 2.5
    assert calls[0][1]["max_depth"] == 1
    assert calls[0][1]["capability"] is cap
    assert st is not None and st.status == "done" and st.result == "finished"


def test_run_goal_unknown_id_returns_none_without_dispatch():
    dispatch = MagicMock()
    svc = GoalService(world_factory=lambda: _FakeWorld({}), dispatch=dispatch)
    assert svc.run_goal(99) is None
    assert not dispatch.called


# ---- client half: GrpcDispatcher ----

def _fake_stub(status="done", found=True, raise_exc=None):
    pb2 = types.SimpleNamespace(
        RunGoalRequest=lambda **kw: types.SimpleNamespace(**kw))
    stub = MagicMock()
    if raise_exc is not None:
        stub.RunGoal.side_effect = raise_exc
    else:
        stub.RunGoal.return_value = types.SimpleNamespace(
            goal_id=7, status=status, result="", found=found)
    return stub, pb2


def test_dispatcher_submit_returns_terminal_status():
    stub, pb2 = _fake_stub(status="done")
    d = GrpcDispatcher("worker:50051", stub_factory=lambda: (stub, pb2))
    cap = Capability(principal="user:u", deny_tools=frozenset({"shell"}))
    out = d.submit(
        7, max_dollars=1.0, channel="api", user_id="u",
        max_depth=1, capability=cap,
    )
    assert out == "done"
    req = stub.RunGoal.call_args.args[0]
    assert req.goal_id == 7 and req.max_dollars == 1.0
    assert req.channel == "api" and req.user_id == "u"
    assert req.max_depth == 1
    assert "\"deny_tools\":[\"shell\"]" in req.capability_json


def test_dispatcher_token_metadata():
    stub, pb2 = _fake_stub()
    d = GrpcDispatcher("w:1", token="s3cret", stub_factory=lambda: (stub, pb2))
    d.submit(1)
    md = dict(stub.RunGoal.call_args.kwargs["metadata"])
    assert md["authorization"] == "Bearer s3cret"


def test_dispatcher_worker_down_returns_none():
    stub, pb2 = _fake_stub(raise_exc=ConnectionError("unreachable"))
    d = GrpcDispatcher("w:1", stub_factory=lambda: (stub, pb2))
    assert d.submit(7) is None


def test_dispatcher_unshared_db_returns_none():
    stub, pb2 = _fake_stub(found=False)
    d = GrpcDispatcher("w:1", stub_factory=lambda: (stub, pb2))
    assert d.submit(7) is None


def test_dispatcher_default_port_and_validation():
    stub, pb2 = _fake_stub()
    d = GrpcDispatcher("workerhost", stub_factory=lambda: (stub, pb2))
    assert d.target == "workerhost:50051"
    with pytest.raises(ValueError):
        GrpcDispatcher("   ")


# ---- config install ----

def test_install_from_config(monkeypatch):
    import maverick.runner as runner_mod
    monkeypatch.setenv("MAVERICK_GRPC_DISPATCH_TARGET", "w:50051")
    installed = {}
    monkeypatch.setattr(runner_mod, "set_dispatcher",
                        lambda d: installed.setdefault("d", d))
    assert install_from_config() is True
    assert isinstance(installed["d"], GrpcDispatcher)
    monkeypatch.delenv("MAVERICK_GRPC_DISPATCH_TARGET")
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", lambda: {})
    assert configured_target() == ""
    assert install_from_config() is False
