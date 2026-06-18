"""Tests for the agent control-plane dashboard pages (replay + agent trust)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app
from maverick_dashboard.control_plane import build_replay, trust_overview

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # Fresh world DB + audit dir per test (MAVERICK_HOME steers data_dir("audit")).
    from maverick import world_model
    from maverick.audit import writer as audit_writer
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_AUDIT_SIGN", raising=False)
    # The no-tenant audit writer is a module-level singleton keyed to the first
    # dir it saw; reset it so record() targets THIS test's MAVERICK_HOME (the
    # sanctioned override per writer.default_audit_log's docstring).
    monkeypatch.setattr(audit_writer, "_default", None)
    audit_writer._defaults.clear()
    yield


def _seed_run() -> int:
    """Create a goal + write a few governed audit events for it; return its id."""
    from maverick.audit import EventKind, record
    from maverick.world_model import open_world
    w = open_world()
    gid = w.create_goal("Vendor payment run")
    record(EventKind.GOAL_START, goal_id=gid, title="Vendor payment run")
    record(EventKind.TOOL_CALL, goal_id=gid, name="browser", input_summary="navigate checkout")
    record(EventKind.CONSENT_PROMPT, goal_id=gid, action="browser.click",
           risk="high", scope="text=Pay now")
    record(EventKind.CONSENT_RESULT, goal_id=gid, action="browser.click",
           decision="approve", source="dashboard")
    record(EventKind.TOOL_CALL, goal_id=gid, name="browser", input_summary="click Pay now")
    record(EventKind.GOAL_END, goal_id=gid, status="done")
    return gid


# ---- replay / flight recorder ----------------------------------------------

def test_build_replay_timeline_and_chain():
    gid = _seed_run()
    rep = build_replay(gid)
    kinds = [e["kind"] for e in rep["entries"]]
    assert "tool_call" in kinds
    assert "consent_prompt" in kinds
    assert "consent_result" in kinds
    assert rep["summary"]["tool_calls"] == 2
    assert rep["summary"]["approvals"] == 1
    assert rep["summary"]["approved"] == 1
    # Default deployment has signing off -> reported honestly as 'unsigned',
    # never silently 'verified'.
    assert rep["chain"]["status"] in ("unsigned", "no_log")
    prompts = [e for e in rep["entries"] if e["kind"] == "consent_prompt"]
    assert prompts and prompts[0]["risk"] == "high"


def test_replay_filters_to_one_goal():
    gid = _seed_run()
    other = _seed_run()
    rep = build_replay(gid)
    # only this run's events; the other run is excluded
    assert rep["summary"]["total"] >= 5
    assert other != gid


def test_replay_api_and_evidence_download():
    gid = _seed_run()
    r = client.get(f"/api/v1/replay/{gid}")
    assert r.status_code == 200
    body = r.json()
    assert body["goal"]["id"] == gid
    assert body["artifact"] == "maverick.run_evidence"
    assert len(body["timeline"]) >= 5
    assert "chain" in body and "summary" in body

    ev = client.get(f"/api/v1/replay/{gid}/evidence")
    assert ev.status_code == 200
    cd = ev.headers.get("content-disposition", "")
    assert "attachment" in cd and f"evidence-goal-{gid}.json" in cd


def test_replay_api_404_for_unknown_goal():
    assert client.get("/api/v1/replay/999999").status_code == 404


def test_replay_page_renders():
    gid = _seed_run()
    assert client.get("/replay").status_code == 200          # index
    r = client.get(f"/replay?goal={gid}")
    assert r.status_code == 200
    assert "Run replay" in r.text


# ---- agent trust / permission graph ----------------------------------------

def _fake_trust(monkeypatch, *, enforced=True):
    import maverick.agent_trust as at
    from maverick.agent_trust import TrustedAgent
    agent = TrustedAgent(
        id="vega", pubkey="ab" * 32, direction="inbound",
        allow_tools=frozenset({"read_file", "web_search"}),
        deny_tools=frozenset({"shell"}), max_risk="medium",
        max_dollars=5.0, data_scopes=frozenset({"crm"}),
    )
    monkeypatch.setattr(at, "load_trust_state", lambda: (enforced, {"vega": agent}))


def test_trust_overview_shapes_registry(monkeypatch):
    _fake_trust(monkeypatch)
    ov = trust_overview()
    assert ov["enforced"] is True
    a = ov["agents"][0]
    assert a["id"] == "vega"
    assert a["direction"] == "inbound"
    assert a["max_risk"] == "medium"
    assert "shell" in a["deny_tools"]
    assert a["active"] is True


def test_trust_api_and_page(monkeypatch):
    _fake_trust(monkeypatch)
    r = client.get("/api/v1/trust/agents")
    assert r.status_code == 200
    assert r.json()["agents"][0]["id"] == "vega"
    p = client.get("/trust")
    assert p.status_code == 200
    assert "vega" in p.text


def test_trust_empty_state_does_not_error(monkeypatch):
    import maverick.agent_trust as at
    monkeypatch.setattr(at, "load_trust_state", lambda: (False, {}))
    ov = trust_overview()
    assert ov["agents"] == []
    assert ov["enforced"] is False
    assert client.get("/trust").status_code == 200
