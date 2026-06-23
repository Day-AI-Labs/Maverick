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
