"""Authorization on /plugins/toggle.

Enabling a plugin loads its code on the next goal -- a control-plane change that
must require admin, like /plugins/install. Regression guard for the gap where
the route checked only same-origin.
"""
from __future__ import annotations

import maverick_dashboard.app as appmod
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(appmod.app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))


def test_toggle_is_gated_on_admin(monkeypatch):
    # Simulate RBAC denying a non-admin caller: the route must consult
    # require_permission("admin") and propagate its 403 (not silently toggle).
    seen = []

    def deny(request, perm):
        seen.append(perm)
        raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(appmod, "require_permission", deny)
    r = client.post("/plugins/toggle", data={"name": "x", "action": "enable"})
    assert r.status_code == 403
    assert "admin" in seen


def test_toggle_works_when_authorized(monkeypatch):
    # With permission granted (the auth-off local-admin case), the gate doesn't
    # block: same-origin + admin pass and the route proceeds (redirect, not 403).
    monkeypatch.setattr(appmod, "require_permission", lambda request, perm: None)
    r = client.post(
        "/plugins/toggle", data={"name": "nonexistent-plugin", "action": "reset"},
        follow_redirects=False,
    )
    assert r.status_code != 403
