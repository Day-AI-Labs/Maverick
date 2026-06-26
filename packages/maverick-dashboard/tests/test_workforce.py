"""Workforce packaging: /workforce page + /api/v1 departments/outcomes/marketplace.

Read-only surfaces over the pack registry and the Operating Record. The autouse
fixture points the world DB at a tmp path so these never touch the real one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    yield


def test_departments_list_includes_finance():
    r = client.get("/api/v1/departments")
    assert r.status_code == 200
    depts = {d["key"]: d for d in r.json()}
    assert "finance" in depts
    assert depts["finance"]["title"] == "Finance"
    assert depts["finance"]["headcount"] > 0


def test_department_detail_has_roster():
    r = client.get("/api/v1/departments/finance")
    assert r.status_code == 200
    body = r.json()
    assert body["roster"], "expected a roster"
    assert {"name", "description", "max_risk"} <= set(body["roster"][0])


def test_unknown_department_404():
    assert client.get("/api/v1/departments/not_a_dept").status_code == 404
    assert client.get("/api/v1/departments/not_a_dept/review").status_code == 404


def test_department_review_composes_sections():
    r = client.get("/api/v1/departments/finance/review")
    assert r.status_code == 200
    body = r.json()
    assert {"department", "delivery", "authority", "learning",
            "governance_note"} <= set(body)
    assert "audit log" in body["governance_note"]


def test_outcomes_has_firm_and_workers():
    r = client.get("/api/v1/outcomes")
    assert r.status_code == 200
    body = r.json()
    assert "firm" in body and "workers" in body
    assert "goals_completed" in body["firm"]


def test_marketplace_packs_grouped_and_searchable():
    grouped = client.get("/api/v1/marketplace/packs").json()
    assert any(d["key"] == "finance" for d in grouped["departments"])
    hits = client.get("/api/v1/marketplace/packs", params={"q": "finance"}).json()
    assert hits["query"] == "finance"
    assert isinstance(hits["results"], list)


def test_marketplace_connectors_count_and_search():
    full = client.get("/api/v1/marketplace/connectors").json()
    assert full["total"] > 50
    filtered = client.get("/api/v1/marketplace/connectors",
                          params={"q": "zendesk"}).json()
    assert filtered["total"] == full["total"]
    assert any(c["name"] == "zendesk" for c in filtered["connectors"])


def test_workforce_page_renders():
    r = client.get("/workforce")
    assert r.status_code == 200
    assert "Workforce" in r.text
    assert "Finance" in r.text
    # The nav link is wired in.
    assert "/workforce" in r.text


# --- deploy a department as a fleet (paid add-on) ---

def test_departments_list_reports_entitlement():
    rows = client.get("/api/v1/departments").json()
    assert all("entitled" in r for r in rows)


def test_deploy_department_creates_a_fleet(tmp_path, monkeypatch):
    # Self-host (no tenant) is entitled by fail-open; isolate the fleets dir.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    r = client.post("/api/v1/departments/finance/deploy")
    assert r.status_code == 201
    fleet = r.json()["fleet"]
    assert fleet["name"] == "dept-finance"
    assert fleet["agents"]
    # It is now a real, runnable fleet.
    assert any(f["name"] == "dept-finance" for f in client.get("/api/v1/fleets").json()["fleets"])


def test_deploy_blocked_without_addon_returns_402(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    import maverick.billing as billing
    monkeypatch.setattr(billing, "feature_allowed", lambda feature, **kw: False)
    r = client.post("/api/v1/departments/finance/deploy")
    assert r.status_code == 402
    assert "add-on" in r.json()["detail"]


def test_deploy_unknown_department_404(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    r = client.post("/api/v1/departments/not_a_dept/deploy")
    assert r.status_code == 404


def test_deploy_managed_roster_without_active_tenant_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    from maverick.paths import reset_tenant, set_tenant
    from maverick.tenant import registry as tenant_registry

    token = set_tenant(None)
    try:
        tenant_registry.create_tenant("acme", plan="free")
        rows = client.get("/api/v1/departments").json()
        assert any(r["key"] == "finance" and r["entitled"] is False for r in rows)
        r = client.post("/api/v1/departments/finance/deploy")
    finally:
        reset_tenant(token)

    assert r.status_code == 402
    assert "active tenant" in r.json()["detail"]


def test_deploy_passes_active_tenant_to_entitlement(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    from maverick.paths import reset_tenant, set_tenant
    from maverick.tenant import registry as tenant_registry

    tenant_registry.create_tenant("acme", plan="free")
    token = set_tenant("acme")
    try:
        r = client.post("/api/v1/departments/finance/deploy")
    finally:
        reset_tenant(token)

    assert r.status_code == 402
    assert "add-on" in r.json()["detail"]
