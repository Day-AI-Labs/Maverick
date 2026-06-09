"""Authentication checks for the gRPC protobuf shim."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from maverick.grpc_api import server as grpc_server
from maverick.grpc_api.service import EventDTO, GoalStatusDTO


class _Codes:
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


class _Pb2Grpc:
    class MaverickServicer:
        pass


class _Pb2:
    @dataclass
    class StartGoalResponse:
        goal_id: int

    @dataclass
    class CancelResponse:
        cancelled: bool

    @dataclass
    class GoalStatus:
        goal_id: int
        status: str = ""
        result: str = ""
        found: bool = True

    @dataclass
    class Event:
        id: int
        goal_id: int
        agent: str
        kind: str
        content: str
        ts: float


class _Context:
    def __init__(self, metadata=()):
        self._metadata = metadata
        self.aborted = None

    def invocation_metadata(self):
        return self._metadata

    def is_active(self):
        return True

    def abort(self, code, details):
        self.aborted = (code, details)
        raise PermissionError(details)


class _Service:
    def __init__(self):
        self.calls = []

    def start_goal(self, *args, **kwargs):
        self.calls.append(("start_goal", args, kwargs))
        return 7

    def stream_episode(self, *args, **kwargs):
        self.calls.append(("stream_episode", args, kwargs))
        yield EventDTO(1, 2, "agent", "kind", "content", 3.0)

    def cancel(self, *args, **kwargs):
        self.calls.append(("cancel", args, kwargs))
        return True

    def status(self, *args, **kwargs):
        self.calls.append(("status", args, kwargs))
        return GoalStatusDTO(2, "done", "ok")


def test_serve_requires_configured_bearer_token(monkeypatch):
    monkeypatch.delenv("MAVERICK_GRPC_BEARER_TOKEN", raising=False)

    with pytest.raises(ValueError, match="requires a bearer token"):
        grpc_server.serve()


@pytest.mark.parametrize("method_name", ["StartGoal", "StreamEpisode", "Cancel", "GetStatus"])
def test_rpc_methods_reject_missing_bearer_token(monkeypatch, method_name):
    monkeypatch.setattr(grpc_server, "_grpc_code", lambda: _Codes)
    svc = _Service()
    servicer = grpc_server._servicer(svc, _Pb2, _Pb2Grpc, bearer_token="secret")
    request = SimpleNamespace(
        title="run", description="", max_dollars=1.0, max_wall_seconds=60.0,
        channel="prod", user_id="victim", goal_id=2, since_id=0, max_seconds=1.0,
    )
    context = _Context()
    call = getattr(servicer, method_name)

    with pytest.raises(PermissionError, match="missing or invalid bearer token"):
        result = call(request, context)
        if method_name == "StreamEpisode":
            list(result)

    assert context.aborted == (_Codes.UNAUTHENTICATED, "missing or invalid bearer token")
    assert svc.calls == []


def test_authorized_calls_reach_all_rpc_methods(monkeypatch):
    monkeypatch.setattr(grpc_server, "_grpc_code", lambda: _Codes)
    svc = _Service()
    servicer = grpc_server._servicer(svc, _Pb2, _Pb2Grpc, bearer_token="secret")
    context = _Context((("authorization", "Bearer secret"),))

    start_request = SimpleNamespace(
        title="run", description="", max_dollars=1.0,
        max_wall_seconds=60.0, channel="prod", user_id="user",
    )
    goal_request = SimpleNamespace(goal_id=2, since_id=0, max_seconds=1.0)

    assert servicer.StartGoal(start_request, context).goal_id == 7
    assert list(servicer.StreamEpisode(goal_request, context))[0].content == "content"
    assert servicer.Cancel(goal_request, context).cancelled is True
    assert servicer.GetStatus(goal_request, context).result == "ok"
    assert [call[0] for call in svc.calls] == [
        "start_goal", "stream_episode", "cancel", "status",
    ]
