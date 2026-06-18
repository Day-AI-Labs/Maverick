"""/metrics exposes per-principal spend so an SRE can see which user is
burning budget, not just the deployment-wide total."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    yield


def test_per_user_spend_gauge_present():
    from maverick.quotas import UsageLedger
    UsageLedger().record("user:alice", 3.25, 100, 50)

    text = client.get("/metrics").text
    assert "# HELP maverick_user_spend_dollars_today" in text
    assert 'maverick_user_spend_dollars_today{principal="user:alice"} 3.2500' in text


def test_no_user_spend_gauge_when_empty():
    text = client.get("/metrics").text
    # No spend recorded -> the per-principal block is omitted (no empty noise).
    assert "maverick_user_spend_dollars_today{" not in text
