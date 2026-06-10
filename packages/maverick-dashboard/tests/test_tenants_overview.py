"""Multi-tenant view (/tenants/overview + /api/v1/tenants/overview)."""
from __future__ import annotations

import maverick_dashboard.auth as auth
import pytest
from fastapi.testclient import TestClient
from maverick.oidc import VerifiedPrincipal


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    yield


def _seed_tenant_with_runs_and_spend():
    """Provision 'acme' with two goals (one done, one active) + $1.25 today."""
    from maverick import tenant_registry as tr
    from maverick.paths import data_dir
    from maverick.quotas import UsageLedger
    from maverick.workspace import Workspace
    from maverick.world_model import WorldModel
    tr.create_tenant("acme", plan="enterprise", display_name="Acme Inc",
                     max_daily_dollars=100)
    w = WorldModel(Workspace("acme").db_path)
    gid = w.create_goal("ship it", "")
    w.set_goal_status(gid, "done")
    w.create_goal("audit logs", "")
    w.close()
    UsageLedger(data_dir("usage", "ledger.json", tenant="acme")).record(
        "user:amy", 1.25, 10, 20)


def test_overview_page_empty_state(monkeypatch, tmp_path):
    r = _client().get("/tenants/overview")
    assert r.status_code == 200
    assert "No tenants provisioned" in r.text


def test_overview_page_rollup(monkeypatch, tmp_path):
    _seed_tenant_with_runs_and_spend()
    from maverick import tenant_registry as tr
    tr.create_tenant("beta")
    tr.suspend_tenant("beta")
    text = _client().get("/tenants/overview").text
    assert "acme" in text and "Acme Inc" in text and "enterprise" in text
    assert "done 1" in text and "pending 1" in text
    assert "$1.25" in text
    assert "$100/day" in text
    # beta: suspended flag + no runs yet.
    assert "suspended" in text and "no runs yet" in text


def test_overview_api_rollup(monkeypatch, tmp_path):
    _seed_tenant_with_runs_and_spend()
    r = _client().get("/api/v1/tenants/overview")
    assert r.status_code == 200
    rows = r.json()["tenants"]
    assert len(rows) == 1
    acme = rows[0]
    assert acme["id"] == "acme" and acme["suspended"] is False
    assert acme["goals"] == {"done": 1, "pending": 1}
    assert acme["total_goals"] == 2
    assert acme["spend_today"] == 1.25
    assert acme["max_daily_dollars"] == 100.0


def _as_user(monkeypatch, name: str) -> dict:
    """OIDC on; the bearer token string is the subject (no real JWT)."""
    monkeypatch.setattr(auth, "oidc_enabled", lambda: True)
    monkeypatch.setattr(
        auth, "verify_oidc_token",
        lambda token, **_kw: VerifiedPrincipal(
            sub=token, issuer="https://issuer.example", audience="maverick",
            claims={"sub": token},
        ),
    )
    return {"Authorization": f"Bearer {name}"}


def test_overview_is_admin_only(monkeypatch, tmp_path):
    _seed_tenant_with_runs_and_spend()
    headers = _as_user(monkeypatch, "mallory")
    # Page: access notice, no roster data (same guard as /tenants).
    page = _client().get("/tenants/overview", headers=headers)
    assert page.status_code == 200
    assert "admin" in page.text and "acme" not in page.text
    # API: explicit 403.
    api = _client().get("/api/v1/tenants/overview", headers=headers)
    assert api.status_code == 403


def test_overview_admin_principal_sees_roster(monkeypatch, tmp_path):
    _seed_tenant_with_runs_and_spend()
    headers = _as_user(monkeypatch, "root")
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:root")
    r = _client().get("/api/v1/tenants/overview", headers=headers)
    assert r.status_code == 200
    assert r.json()["tenants"][0]["id"] == "acme"
