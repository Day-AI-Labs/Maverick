"""POST /api/v1/outcomes -- the Consequence Engine's HTTP ingestion entrypoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from maverick import consequence as cq
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    monkeypatch.setattr("maverick.consequence.shared", lambda: store)
    yield store


def test_record_outcome_endpoint(_isolated):
    resp = client.post("/api/v1/outcomes", json={
        "goal_id": 1, "episode_id": 7, "value": 1.0, "kind": "invoice_paid"})
    assert resp.status_code == 204
    assert _isolated.resolve(1, 7) == 1.0


def test_record_outcome_clamps_value(_isolated):
    resp = client.post("/api/v1/outcomes", json={
        "goal_id": 2, "episode_id": 3, "value": 5.0})
    assert resp.status_code == 204
    assert _isolated.resolve(2, 3) == 1.0


def test_record_outcome_rejects_bad_body():
    resp = client.post("/api/v1/outcomes", json={"goal_id": "nope"})
    assert resp.status_code == 422   # FastAPI validation
