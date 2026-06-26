"""SCIM 2.0 user provisioning endpoints.

Hermetic: HOME/MAVERICK_HOME under tmp, the SCIM bearer set on, the world DB and
USER_TEMPLATES isolated like the other dashboard tests. Exercises the IdP
lifecycle (create -> read -> filter -> deprovision -> delete), auth gating, and
that the surface is invisible (404) when no SCIM token is configured.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

_TOKEN = "scim-secret-token-xyz"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _auth(token: str = _TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAVERICK_SCIM_TOKEN", _TOKEN)
    return _client()


def _make_user(client, username="alice@example.com", **extra):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": username,
        "name": {"givenName": "Alice", "familyName": "Smith"},
        "emails": [{"value": username, "primary": True}],
        "active": True,
        **extra,
    }
    return client.post("/scim/v2/Users", json=payload, headers=_auth())


class TestAuth:
    def test_disabled_returns_404(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_SCIM_TOKEN", raising=False)
        r = _client().get("/scim/v2/Users", headers=_auth())
        assert r.status_code == 404

    def test_missing_bearer_401(self, client):
        r = client.get("/scim/v2/Users")
        assert r.status_code == 401
        assert r.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]

    def test_wrong_bearer_401(self, client):
        r = client.get("/scim/v2/Users", headers=_auth("nope"))
        assert r.status_code == 401

    def test_comma_separated_rotation_accepts_old_and_new(self, monkeypatch):
        # During a rotation, old + new are both valid; a retired token is not.
        monkeypatch.setenv("MAVERICK_SCIM_TOKEN", "old-tok,new-tok")  # pragma: allowlist secret
        c = _client()
        assert c.get("/scim/v2/Users", headers=_auth("old-tok")).status_code == 200
        assert c.get("/scim/v2/Users", headers=_auth("new-tok")).status_code == 200
        assert c.get("/scim/v2/Users", headers=_auth("retired")).status_code == 401

    def test_sha256_hashed_secret_keeps_plaintext_out_of_env(self, monkeypatch):
        import hashlib
        tok = "plain-scim-token"  # pragma: allowlist secret
        digest = hashlib.sha256(tok.encode()).hexdigest()
        monkeypatch.setenv("MAVERICK_SCIM_TOKEN", f"sha256:{digest}")
        c = _client()
        assert c.get("/scim/v2/Users", headers=_auth(tok)).status_code == 200
        assert c.get("/scim/v2/Users", headers=_auth("wrong")).status_code == 401

    def test_deprovision_revokes_live_sessions(self, client):
        # Deprovisioning must end current access (#58), not just future logins:
        # the SCIM user's identifiers get a revocation epoch so live sessions die.
        from maverick_dashboard import session_revocation as sr
        r = _make_user(client, externalId="okta-sub-123")
        uid = r.json()["id"]
        assert sr.revocation_epoch("okta-sub-123") == 0.0
        client.delete(f"/scim/v2/Users/{uid}", headers=_auth())
        assert sr.revocation_epoch("okta-sub-123") > 0.0   # externalId (= OIDC sub)
        assert sr.revocation_epoch("alice@example.com") > 0.0  # userName too

    def test_deprovision_revokes_pairwise_sub_via_directory(self, client):
        # Entra case: the OIDC `sub` is pairwise and appears in NO SCIM attribute.
        # The subject directory recorded it at login keyed by the user's email;
        # deprovision must look it up and revoke it, not just the SCIM ids.
        from maverick_dashboard import session_revocation as sr
        from maverick_dashboard import subject_directory as sd
        # Login recorded: email/oid -> the pairwise session sub.
        sd.record_login("pairwise-AAA", ["bob@example.com", "aad-oid-9"])
        r = _make_user(client, username="bob@example.com", externalId="aad-oid-9")
        uid = r.json()["id"]
        assert sr.revocation_epoch("pairwise-AAA") == 0.0   # not a SCIM attribute
        client.patch(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        # The pairwise sub -- the actual session key -- is now revoked.
        assert sr.revocation_epoch("pairwise-AAA") > 0.0

    def test_hard_delete_forgets_directory_entry(self, client):
        from maverick_dashboard import subject_directory as sd
        sd.record_login("pairwise-BBB", ["carol@example.com"])
        r = _make_user(client, username="carol@example.com")
        uid = r.json()["id"]
        client.delete(f"/scim/v2/Users/{uid}", headers=_auth())
        # The mapping shouldn't outlive the deleted account.
        assert sd.subs_for(["carol@example.com"]) == set()


class TestDiscovery:
    def test_service_provider_config(self, client):
        r = client.get("/scim/v2/ServiceProviderConfig", headers=_auth())
        assert r.status_code == 200
        assert r.json()["patch"]["supported"] is True

    def test_resource_types(self, client):
        r = client.get("/scim/v2/ResourceTypes", headers=_auth())
        assert r.status_code == 200
        assert r.json()[0]["endpoint"] == "/Users"


class TestLifecycle:
    def test_create_returns_201_with_id(self, client):
        r = _make_user(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["userName"] == "alice@example.com"
        assert body["id"]
        assert body["active"] is True
        assert body["emails"][0]["value"] == "alice@example.com"
        assert body["meta"]["resourceType"] == "User"

    def test_create_provisions_tenant(self, client):
        uid = _make_user(client).json()["id"]
        from maverick.tenant import registry
        assert registry.get_tenant(uid) is not None

    def test_duplicate_username_409(self, client):
        _make_user(client)
        r = _make_user(client)
        assert r.status_code == 409
        assert r.json()["scimType"] == "uniqueness"

    def test_missing_username_400(self, client):
        r = client.post("/scim/v2/Users", json={"active": True}, headers=_auth())
        assert r.status_code == 400

    def test_get_by_id(self, client):
        uid = _make_user(client).json()["id"]
        r = client.get(f"/scim/v2/Users/{uid}", headers=_auth())
        assert r.status_code == 200 and r.json()["id"] == uid

    def test_get_unknown_404(self, client):
        r = client.get("/scim/v2/Users/does-not-exist", headers=_auth())
        assert r.status_code == 404

    def test_list_and_filter(self, client):
        _make_user(client, username="a@x.com")
        _make_user(client, username="b@x.com")
        r = client.get("/scim/v2/Users", headers=_auth())
        assert r.json()["totalResults"] == 2
        # userName eq filter (the IdP existence probe).
        r2 = client.get('/scim/v2/Users?filter=userName eq "a@x.com"', headers=_auth())
        body = r2.json()
        assert body["totalResults"] == 1
        assert body["Resources"][0]["userName"] == "a@x.com"

    def test_unsupported_filter_400(self, client):
        r = client.get('/scim/v2/Users?filter=displayName co "z"', headers=_auth())
        assert r.status_code == 400
        assert r.json()["scimType"] == "invalidFilter"

    def test_pagination(self, client):
        for i in range(3):
            _make_user(client, username=f"u{i}@x.com")
        r = client.get("/scim/v2/Users?startIndex=1&count=2", headers=_auth())
        body = r.json()
        assert body["totalResults"] == 3 and body["itemsPerPage"] == 2

    def test_put_replaces(self, client):
        uid = _make_user(client).json()["id"]
        r = client.put(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "alice@example.com", "displayName": "Alice R", "active": True,
        })
        assert r.status_code == 200 and r.json()["displayName"] == "Alice R"

    def test_patch_deprovision_suspends_tenant(self, client):
        uid = _make_user(client).json()["id"]
        from maverick.tenant import registry
        assert registry.get_tenant(uid).active is True
        # Okta deprovision: PATCH replace active=false.
        r = client.patch(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        assert r.status_code == 200 and r.json()["active"] is False
        assert registry.get_tenant(uid).active is False

    def test_patch_azure_no_path_form(self, client):
        uid = _make_user(client).json()["id"]
        r = client.patch(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"active": False}}],
        })
        assert r.status_code == 200 and r.json()["active"] is False

    def test_patch_unsupported_400(self, client):
        uid = _make_user(client).json()["id"]
        r = client.patch(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "nickName", "value": "x"}],
        })
        assert r.status_code == 400

    def test_delete_removes_user_and_tenant(self, client):
        uid = _make_user(client).json()["id"]
        r = client.delete(f"/scim/v2/Users/{uid}", headers=_auth())
        assert r.status_code == 204
        assert client.get(f"/scim/v2/Users/{uid}", headers=_auth()).status_code == 404
        from maverick.tenant import registry
        assert registry.get_tenant(uid) is None

    def test_patch_tenant_suspend_failure_does_not_commit_scim_inactive(self, client, monkeypatch):
        uid = _make_user(client).json()["id"]
        from maverick.tenant import registry

        def fail_suspend(_uid):
            raise RuntimeError("simulated suspend failure")

        monkeypatch.setattr(registry, "suspend_tenant", fail_suspend)
        r = client.patch(f"/scim/v2/Users/{uid}", headers=_auth(), json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        assert r.status_code == 500
        assert client.get(f"/scim/v2/Users/{uid}", headers=_auth()).json()["active"] is True
        assert registry.get_tenant(uid).active is True

    def test_delete_tenant_failure_keeps_scim_user_for_retry(self, client, monkeypatch):
        uid = _make_user(client).json()["id"]
        from maverick.tenant import registry

        def fail_delete(_uid):
            raise RuntimeError("simulated delete failure")

        monkeypatch.setattr(registry, "delete_tenant", fail_delete)
        r = client.delete(f"/scim/v2/Users/{uid}", headers=_auth())
        assert r.status_code == 500
        assert client.get(f"/scim/v2/Users/{uid}", headers=_auth()).status_code == 200
        assert registry.get_tenant(uid) is not None
