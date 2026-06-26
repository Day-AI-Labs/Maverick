"""Exposed-deployment hardening (issue #468): dashboard resource limits.

Covers:
  * SSE goal-event stream concurrency cap (503 past the limit).
  * Per-client goal rate limiting (one client's flood doesn't 429 another).
  * A2A JSON-RPC body-size cap (oversized body rejected with 413).
  * /healthz minimal payload when an auth token is configured.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _setup(monkeypatch, tmp_path):
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    return world_model.WorldModel(db)


# ---------- task 1: SSE concurrent-connection cap ----------

def test_sse_stream_returns_503_when_cap_exhausted(monkeypatch, tmp_path):
    w = _setup(monkeypatch, tmp_path)
    gid = w.create_goal("g", "d")
    w.set_goal_status(gid, "done")

    from maverick_dashboard import app as dash_app

    # Simulate the cap being fully consumed by other live streams: the route
    # checks ``sem.locked()`` and returns 503 before ever acquiring, so a stub
    # reporting "locked" is enough (and avoids touching a real event loop).
    class _FullSem:
        def locked(self):
            return True

    monkeypatch.setattr(dash_app, "_get_sse_semaphore", lambda: _FullSem())

    r = _client().get(f"/api/goal/{gid}/events/stream")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


def test_sse_stream_serves_when_capacity_available(monkeypatch, tmp_path):
    w = _setup(monkeypatch, tmp_path)
    gid = w.create_goal("g", "d")
    w.append_event(gid, "planner", "plan", "hi")
    w.set_goal_status(gid, "done")

    from maverick_dashboard import app as dash_app
    # Fresh, fully-available semaphore.
    monkeypatch.setattr(dash_app, "_get_sse_semaphore", lambda: asyncio.Semaphore(4))

    r = _client().get(f"/api/goal/{gid}/events/stream")
    assert r.status_code == 200
    assert "event: terminal" in r.text


# ---------- task 2: per-client goal rate limiting ----------

def _reset_rl():
    from maverick_dashboard import app as dash_app
    dash_app._goal_times.clear()
    dash_app._goal_times_global.clear()


def test_rate_limit_is_per_client(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _reset_rl()
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "2")
    # Keep the global ceiling well above the per-client cap so it doesn't fire.
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_GLOBAL_PER_MIN", "100")

    from fastapi import HTTPException
    from maverick_dashboard import app as dash_app

    class _Req:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    a = _Req("1.1.1.1")
    b = _Req("2.2.2.2")

    # Client A exhausts its own window (cap 2).
    dash_app.check_goal_rate_limit(a)
    dash_app.check_goal_rate_limit(a)
    with pytest.raises(HTTPException) as exc:
        dash_app.check_goal_rate_limit(a)
    assert exc.value.status_code == 429

    # Client B is unaffected by A's flood.
    dash_app.check_goal_rate_limit(b)
    dash_app.check_goal_rate_limit(b)


def test_rate_limit_global_ceiling(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _reset_rl()
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "5")
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_GLOBAL_PER_MIN", "3")

    from fastapi import HTTPException
    from maverick_dashboard import app as dash_app

    class _Req:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    # Three distinct clients, each under their own cap, still trip the global
    # ceiling of 3.
    dash_app.check_goal_rate_limit(_Req("1.1.1.1"))
    dash_app.check_goal_rate_limit(_Req("2.2.2.2"))
    dash_app.check_goal_rate_limit(_Req("3.3.3.3"))
    with pytest.raises(HTTPException) as exc:
        dash_app.check_goal_rate_limit(_Req("4.4.4.4"))
    assert exc.value.status_code == 429


# ---------- task 3: A2A JSON-RPC body-size cap ----------

def test_a2a_oversized_body_rejected(monkeypatch):
    pytest.importorskip("fastapi")
    import maverick.a2a as a2a
    from fastapi import FastAPI

    monkeypatch.setenv("MAVERICK_A2A_ENABLED", "1")
    monkeypatch.setenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", "1")
    monkeypatch.delenv("MAVERICK_A2A_TOKEN", raising=False)

    app = FastAPI()
    a2a.mount(app)
    client = TestClient(app)

    # >256 KiB body must be rejected before parsing/auth.
    big = "x" * (300 * 1024)
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
           "params": {"pad": big}}
    r = client.post("/a2a/v1", json=rpc)
    assert r.status_code == 413
    assert r.json()["error"]["message"] == "request body too large"

    # A small body still works.
    small = {"jsonrpc": "2.0", "id": 2, "method": "tasks/get",
             "params": {"id": "nope"}}
    r = client.post("/a2a/v1", json=small)
    assert r.status_code == 200


# ---------- task 4: /healthz minimal payload under a token ----------

def test_healthz_minimal_payload_when_token_set(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "sekret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    r = _client().get("/healthz")
    assert r.status_code == 200
    body = r.json()
    # Only the status leaks; no llm_key / in-flight gauge / db path.
    assert body == {"status": "ok"}
    assert "checks" not in body


def test_healthz_full_payload_without_token(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    r = _client().get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "checks" in body
    assert "llm_key" in body["checks"]


def test_rate_limit_dict_does_not_grow_unbounded(monkeypatch, tmp_path):
    # A stream of distinct one-shot rate-limit keys (many principals / direct
    # client IPs) must not grow _goal_times without bound: the per-call sweep
    # prunes every key whose window has fully expired, not just already-empty ones.
    _setup(monkeypatch, tmp_path)
    _reset_rl()
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "100")
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_GLOBAL_PER_MIN", "100000")
    from maverick_dashboard import app as dash_app

    clock = [1000.0]
    monkeypatch.setattr(dash_app.time, "monotonic", lambda: clock[0])

    for i in range(50):
        dash_app.check_goal_rate_limit(source=f"client-{i}")
    assert len(dash_app._goal_times) == 50

    # Advance past the 60s window so every prior entry is stale, then one more
    # distinct call: the sweep prunes the 50 now-empty keys.
    clock[0] = 1100.0
    dash_app.check_goal_rate_limit(source="client-new")
    assert len(dash_app._goal_times) == 1  # only the live key remains
