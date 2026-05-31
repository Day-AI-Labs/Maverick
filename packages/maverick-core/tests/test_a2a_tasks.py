"""A2A task lifecycle: message/send, message/stream, tasks/get|cancel,
push config, auth, and budget clamping. Goals are faked via an injected
runner so these never touch an LLM or sandbox."""
import asyncio

import pytest
from maverick.a2a_tasks import (
    _AUTH_REQUIRED,
    TaskEngine,
    _RpcError,
)


def _fake_runner(text, *, max_dollars, max_wall, max_depth):
    return f"did:{text} (<=${max_dollars})"


def _msg(text):
    return {"message": {"role": "user", "parts": [{"kind": "text", "text": text}]}}


def _collect(agen):
    async def _run():
        return [e async for e in agen]
    return asyncio.run(_run())


# ---- message/send ----------------------------------------------------

def test_send_completes_with_artifact():
    eng = TaskEngine(runner=_fake_runner)
    task = asyncio.run(eng.send(_msg("hello")))
    assert task["kind"] == "task"
    assert task["status"]["state"] == "completed"
    assert task["artifacts"][0]["parts"][0]["text"].startswith("did:hello")
    states = [s["state"] for s in task["metadata"]["statusHistory"]]
    assert states == ["submitted", "working", "completed"]
    # inbound message echoed into history with task/context ids stamped
    assert task["history"][0]["taskId"] == task["id"]


def test_empty_message_is_rejected():
    eng = TaskEngine(runner=_fake_runner)
    task = asyncio.run(eng.send({"message": {"role": "user", "parts": []}}))
    assert task["status"]["state"] == "rejected"


def test_runner_failure_marks_failed():
    def boom(text, **k):
        raise RuntimeError("kaboom")
    eng = TaskEngine(runner=boom)
    task = asyncio.run(eng.send(_msg("hi")))
    assert task["status"]["state"] == "failed"
    assert "kaboom" in task["artifacts"][0]["parts"][0]["text"]


# ---- message/stream --------------------------------------------------

def test_stream_event_sequence():
    eng = TaskEngine(runner=_fake_runner)
    events = _collect(eng.stream(_msg("go")))
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "task"               # initial snapshot
    assert "status-update" in kinds
    assert "artifact-update" in kinds
    last = events[-1]
    assert last["kind"] == "status-update"
    assert last["final"] is True
    assert last["status"]["state"] == "completed"
    art = next(e for e in events if e["kind"] == "artifact-update")
    assert art["artifact"]["parts"][0]["text"].startswith("did:go")


# ---- tasks/get + tasks/cancel + push config --------------------------

def test_get_and_cancel():
    eng = TaskEngine(runner=_fake_runner)
    task = asyncio.run(eng.send(_msg("x")))
    tid = task["id"]
    assert eng.get({"id": tid})["id"] == tid
    # cancelling an already-terminal task leaves it terminal
    assert eng.cancel({"id": tid})["status"]["state"] == "completed"
    with pytest.raises(_RpcError):
        eng.get({"id": "nope"})


def test_cancel_pending_task():
    eng = TaskEngine(runner=_fake_runner)
    t = eng._new_task(_msg("later"))  # created, not yet run
    assert eng.cancel({"id": t.id})["status"]["state"] == "canceled"


def test_push_config_set_and_get():
    eng = TaskEngine(runner=_fake_runner)
    t = eng._new_task(_msg("x"))
    cfg = {"url": "https://client.example/wh", "token": "abc"}
    res = eng.set_push_config({"taskId": t.id, "pushNotificationConfig": cfg})
    assert res["pushNotificationConfig"]["url"] == cfg["url"]
    assert eng.get_push_config({"taskId": t.id})["pushNotificationConfig"] == cfg
    with pytest.raises(_RpcError):  # url is required
        eng.set_push_config({"taskId": t.id, "pushNotificationConfig": {}})


# ---- auth + budget clamping ------------------------------------------

def test_auth_model(monkeypatch):
    eng = TaskEngine(runner=_fake_runner)
    monkeypatch.delenv("MAVERICK_A2A_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", raising=False)
    # no token + no opt-out -> refuse
    err = eng.auth_error(None)
    assert err and err["code"] == _AUTH_REQUIRED
    # explicit localhost opt-out -> allowed
    monkeypatch.setenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", "1")
    assert eng.auth_error(None) is None
    # token set -> bearer enforced
    monkeypatch.delenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("MAVERICK_A2A_TOKEN", "sekret")
    assert eng.auth_error(None) is not None
    assert eng.auth_error("Bearer wrong") is not None
    assert eng.auth_error("Bearer sekret") is None


def test_budget_is_clamped_to_ceiling(monkeypatch):
    monkeypatch.setenv("MAVERICK_A2A_MAX_DOLLARS", "2.5")
    captured = {}

    def rec(text, *, max_dollars, max_wall, max_depth):
        captured.update(d=max_dollars)
        return "ok"

    eng = TaskEngine(runner=rec)
    asyncio.run(eng.send(_msg("hi")))
    assert captured["d"] == 2.5


# ---- HTTP wiring (FastAPI) -------------------------------------------

def test_http_endpoint_send_and_card(monkeypatch):
    pytest.importorskip("fastapi")
    import maverick.a2a as a2a
    import maverick.a2a_tasks as a2at
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(a2at, "_default_runner",
                        lambda text, **k: f"ran:{text}")
    monkeypatch.setenv("MAVERICK_A2A_ENABLED", "1")
    monkeypatch.setenv("MAVERICK_A2A_TOKEN", "tok")
    monkeypatch.delenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", raising=False)

    app = FastAPI()
    a2a.mount(app)
    client = TestClient(app)

    rpc = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
           "params": _msg("hello")}
    # no bearer -> 401
    assert client.post("/a2a/v1", json=rpc).status_code == 401
    # with bearer -> completed task
    r = client.post("/a2a/v1", headers={"Authorization": "Bearer tok"}, json=rpc)
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["status"]["state"] == "completed"
    assert "ran:hello" in result["artifacts"][0]["parts"][0]["text"]

    # the card now advertises the backed capabilities
    card = client.get("/.well-known/agent-card.json").json()
    assert card["capabilities"]["streaming"] is True
    assert card["capabilities"]["pushNotifications"] is True
    assert card["url"].endswith("/a2a/v1")


def test_http_stream_emits_sse(monkeypatch):
    pytest.importorskip("fastapi")
    import maverick.a2a as a2a
    import maverick.a2a_tasks as a2at
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(a2at, "_default_runner", lambda text, **k: f"ran:{text}")
    monkeypatch.setenv("MAVERICK_A2A_ENABLED", "1")
    monkeypatch.setenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", "1")
    monkeypatch.delenv("MAVERICK_A2A_TOKEN", raising=False)

    app = FastAPI()
    a2a.mount(app)
    client = TestClient(app)
    rpc = {"jsonrpc": "2.0", "id": 2, "method": "message/stream",
           "params": _msg("go")}
    r = client.post("/a2a/v1", json=rpc)
    assert r.status_code == 200
    body = r.text
    assert "status-update" in body
    assert "artifact-update" in body
    assert "ran:go" in body
