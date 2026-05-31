"""A2A Agent Card integration tests for the production dashboard app."""
from __future__ import annotations

import importlib

import pytest


def _reload_dashboard_app(monkeypatch):
    monkeypatch.setenv("HOME", "/nonexistent-a2a-dashboard-test")
    import maverick_dashboard.app as dashboard_app

    return importlib.reload(dashboard_app)


@pytest.mark.parametrize("path", ["/.well-known/agent-card.json", "/.well-known/agent.json"])
def test_dashboard_serves_a2a_agent_card_when_enabled(monkeypatch, path):
    monkeypatch.setenv("MAVERICK_A2A_ENABLED", "1")
    # Discovery should remain reachable even when the dashboard control surface
    # is protected by a bearer token.
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
    dashboard_app = _reload_dashboard_app(monkeypatch)

    from fastapi.testclient import TestClient

    client = TestClient(dashboard_app.app)
    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Maverick"
    assert body["protocolVersion"] == "1.0"


def test_dashboard_omits_a2a_agent_card_when_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_A2A_ENABLED", raising=False)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    dashboard_app = _reload_dashboard_app(monkeypatch)

    from fastapi.testclient import TestClient

    client = TestClient(dashboard_app.app)

    assert client.get("/.well-known/agent-card.json").status_code == 404
