"""Dispatch a goal AS a fleet agent from the operator console.

POST /api/v1/fleets/<fleet>/run runs a governed goal under the agent's RBAC
role capability + its own audit principal (``agent:<fleet>.<agent>``),
mirroring ``maverick fleet run`` -- so the oversight control plane governs the
work. Owner-scoped; mutating POST carries a same-origin Origin (CSRF contract).

Hermetic: OIDC off, HOME/MAVERICK_HOME + DEFAULT_DB isolated, the provider-key
gate and rate limiter stubbed, and run_goal_in_thread replaced with a capturing
stub so no real goal runs.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick_dashboard.api as api
    monkeypatch.setattr(api, "_any_provider_key_set", lambda: True)
    import maverick_dashboard.app as dash_app
    monkeypatch.setattr(dash_app, "check_goal_rate_limit", lambda request: None)


def _save_fleet(owner="user:dana"):
    from maverick.fleet import Fleet, FleetAgent, save_fleet
    save_fleet(Fleet(name="acme", owner=owner, agents=(
        FleetAgent("researcher", "analyst", "digs through sources"),
        FleetAgent("coder", "engineer"),
    )))


def _stub_runner(monkeypatch):
    calls: list[dict] = []

    def _stub(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return "ok"

    import maverick.runner as runner
    monkeypatch.setattr(runner, "run_goal_in_thread", _stub)
    return calls


def test_dispatch_runs_agent_under_role_capability(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    calls = _stub_runner(monkeypatch)

    r = _client().post("/api/v1/fleets/acme/run",
                       json={"agent": "coder", "prompt": "ship the build"})
    assert r.status_code == 201, r.text
    body = r.json()
    gid = body["goal_id"]
    assert body["principal"] == "agent:acme.coder"
    assert body["role"] == "engineer"

    # the goal exists, owned by the fleet owner (so it shows in the owner's views)
    from maverick.world_model import WorldModel
    g = WorldModel(tmp_path / "world.db").get_goal(gid)
    assert g is not None and g.owner == "user:dana"

    # the run is recorded against the fleet for the supervisor trail
    from maverick.fleet import load_runs
    assert any(rr["agent"] == "coder" and rr["goal_id"] == gid
               for rr in load_runs("acme"))

    # the background runner got the role-scoped capability + the agent principal
    assert calls, "expected run_goal_in_thread to be scheduled"
    kw = calls[0]["kwargs"]
    assert kw["user_id"] == "agent:acme.coder"
    assert kw["capability"] is not None
    assert kw["capability"].principal == "agent:acme.coder"


def test_dispatch_attenuates_legacy_bad_roles_to_caller_capability(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {
            "role_assignments": {"user:eve": "restricted"},
            "roles": {"restricted": {"allow_tools": ["read_file"]}},
        },
    )
    import maverick_dashboard.api as api
    monkeypatch.setattr(api, "caller_principal", lambda request: "user:eve")
    monkeypatch.setattr(api, "is_dashboard_admin", lambda p: False)
    from maverick.fleet import Fleet, FleetAgent, save_fleet
    save_fleet(Fleet(name="acme", owner="user:eve", agents=(
        FleetAgent("blank", ""),
        FleetAgent("ghost", "ghost"),
    )))
    calls = _stub_runner(monkeypatch)

    for agent in ("blank", "ghost"):
        r = _client().post(
            "/api/v1/fleets/acme/run",
            json={"agent": agent, "prompt": "try to run shell"},
        )
        assert r.status_code == 201, r.text

    for agent, call in zip(("blank", "ghost"), calls, strict=True):
        cap = call["kwargs"]["capability"]
        assert cap.principal == f"agent:acme.{agent}"
        assert cap.permits("read_file") is True
        assert cap.permits("shell") is False


def test_dispatch_unknown_agent_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    _stub_runner(monkeypatch)
    r = _client().post("/api/v1/fleets/acme/run",
                       json={"agent": "ghost", "prompt": "x"})
    assert r.status_code == 404


def test_dispatch_unknown_fleet_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _stub_runner(monkeypatch)
    r = _client().post("/api/v1/fleets/nope/run",
                       json={"agent": "coder", "prompt": "x"})
    assert r.status_code == 404


def test_dispatch_requires_prompt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    _stub_runner(monkeypatch)
    r = _client().post("/api/v1/fleets/acme/run",
                       json={"agent": "coder", "prompt": "   "})
    assert r.status_code == 400


def test_dispatch_owner_scoped_404_for_non_owner(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet(owner="user:dana")
    _stub_runner(monkeypatch)
    # A non-owner, non-admin caller can't dispatch to (or even see) the fleet.
    import maverick_dashboard.api as api
    monkeypatch.setattr(api, "caller_principal", lambda request: "user:eve")
    monkeypatch.setattr(api, "is_dashboard_admin", lambda p: False)
    r = _client().post("/api/v1/fleets/acme/run",
                       json={"agent": "coder", "prompt": "x"})
    assert r.status_code == 404  # cross-owner fleet hidden, never revealed


def test_fleets_page_has_run_form(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    text = _client().get("/fleets").text
    assert 'class="fleet-run-form"' in text
    assert "/api/v1/fleets/" in text  # the dispatch target
