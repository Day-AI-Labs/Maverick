"""SAML 2.0 SP browser SSO.

Hermetic: no pysaml2 and no real assertion. The library calls (``_client`` /
``verify_acs_response`` / ``login_redirect_url`` / ``sp_metadata_xml``) are
isolated and monkeypatched, so the routing, NameID->principal mapping, session
minting, relay-state safety and fail-closed gating are all exercised without a
live IdP. (A real Okta/Entra round-trip still needs certifying separately.)
"""

from __future__ import annotations

import maverick_dashboard.saml as saml_mod
import pytest
from fastapi.testclient import TestClient
from maverick.web_session import verify_session
from maverick_dashboard.app import app

SECRET = "saml-unit-session-secret"  # pragma: allowlist secret

ENABLED_CFG = {
    "sp_entity_id": "https://us.example.com/saml/metadata",
    "acs_url": "https://us.example.com/saml/acs",
    "idp_metadata_url": "https://idp.example.com/metadata",
}


def _client() -> TestClient:
    return TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(saml_mod, "_auth_saml_cfg", lambda: dict(ENABLED_CFG))
    monkeypatch.setattr(saml_mod, "_session_secret", lambda: SECRET)


# --- gating -----------------------------------------------------------------


def test_enabled_requires_full_config(monkeypatch):
    monkeypatch.setattr(saml_mod, "_auth_saml_cfg", dict)
    assert saml_mod.saml_enabled() is False
    monkeypatch.setattr(
        saml_mod, "_auth_saml_cfg", lambda: {"sp_entity_id": "x"}
    )  # missing acs + idp
    assert saml_mod.saml_enabled() is False
    monkeypatch.setattr(saml_mod, "_auth_saml_cfg", lambda: dict(ENABLED_CFG))
    assert saml_mod.saml_enabled() is True


def test_routes_404_when_disabled(monkeypatch):
    monkeypatch.setattr(saml_mod, "_auth_saml_cfg", dict)
    c = _client()
    assert c.get("/saml/metadata").status_code == 404
    assert c.get("/saml/login", follow_redirects=False).status_code == 404
    assert c.post("/saml/acs", data={"SAMLResponse": "x"}).status_code == 404


# --- mapping + session ------------------------------------------------------


class _FakeNID:
    text = "alice@example.com"


class _FakeResp:
    name_id = _FakeNID()

    def get_identity(self):
        return {"email": ["alice@example.com"], "groups": ["admins"]}

    def get_subject(self):
        return _FakeNID()


def test_extract_identity_maps_nameid_and_attrs():
    ident = saml_mod.extract_identity(_FakeResp())
    assert ident.name_id == "alice@example.com"
    assert ident.principal == "user:alice@example.com"
    assert ident.attributes["groups"] == ["admins"]


def test_extract_identity_requires_nameid():
    class _NoNID:
        name_id = None

        def get_subject(self):
            raise RuntimeError("no subject")

    with pytest.raises(saml_mod.SamlUnavailable):
        saml_mod.extract_identity(_NoNID())


def test_extract_identity_rejects_none():
    with pytest.raises(saml_mod.SamlUnavailable):
        saml_mod.extract_identity(None)


def test_mint_session_roundtrips_through_shared_verifier():
    cookie = saml_mod.mint_session_cookie("bob@example.com", secret=SECRET)
    payload = verify_session(cookie, SECRET)
    assert payload and payload["sub"] == "bob@example.com" and payload["exp"] > 0
    assert isinstance(payload["iat"], int) and payload["iat"] > 0


def test_mint_session_after_revocation_has_fresh_iat(monkeypatch, tmp_path):
    from maverick_dashboard import session_revocation as sr

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    sr.revoke_principal("bob@example.com", at=999.0)
    monkeypatch.setattr(saml_mod.time, "time", lambda: 1000.0)

    cookie = saml_mod.mint_session_cookie("bob@example.com", secret=SECRET)
    payload = verify_session(cookie, SECRET, now=1000.0)

    assert payload
    assert payload["iat"] == 1000
    assert payload["exp"] == 1000 + saml_mod._SESSION_TTL
    assert sr.is_revoked(payload["sub"], payload["iat"]) is False


def test_mint_session_requires_secret():
    with pytest.raises(saml_mod.SamlUnavailable):
        saml_mod.mint_session_cookie("bob", secret="")


# --- ACS --------------------------------------------------------------------


def test_acs_verifies_sets_session_and_redirects(_enabled, monkeypatch):
    monkeypatch.setattr(
        saml_mod,
        "verify_acs_response",
        lambda r: saml_mod.SamlIdentity(name_id="alice@example.com"),
    )
    res = _client().post(
        "/saml/acs", data={"SAMLResponse": "signed", "RelayState": "/goals"}, follow_redirects=False
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/goals"
    cookie = res.cookies.get("mvk_session")
    assert cookie
    payload = verify_session(cookie, SECRET)
    assert payload["sub"] == "alice@example.com"


def test_acs_missing_response_is_400(_enabled):
    res = _client().post("/saml/acs", data={}, follow_redirects=False)
    assert res.status_code == 400


def test_acs_verification_failure_is_401(_enabled, monkeypatch):
    def _boom(_r):
        raise ValueError("bad signature")

    monkeypatch.setattr(saml_mod, "verify_acs_response", _boom)
    res = _client().post("/saml/acs", data={"SAMLResponse": "tampered"}, follow_redirects=False)
    assert res.status_code == 401
    assert "did not verify" in res.text


def test_acs_blocks_open_redirect_relay_state(_enabled, monkeypatch):
    monkeypatch.setattr(
        saml_mod, "verify_acs_response", lambda r: saml_mod.SamlIdentity(name_id="a")
    )
    res = _client().post(
        "/saml/acs",
        data={"SAMLResponse": "x", "RelayState": "https://evil.example/"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/"  # external relay rejected -> default


def test_acs_503_without_pysaml2(_enabled, monkeypatch):
    def _boom(_r):
        raise saml_mod.SamlUnavailable("needs pysaml2")

    monkeypatch.setattr(saml_mod, "verify_acs_response", _boom)
    res = _client().post("/saml/acs", data={"SAMLResponse": "x"}, follow_redirects=False)
    assert res.status_code == 503


# --- login + metadata -------------------------------------------------------


def test_login_redirects_to_idp(_enabled, monkeypatch):
    monkeypatch.setattr(
        saml_mod,
        "login_redirect_url",
        lambda cfg=None, relay_state="/": "https://idp.example.com/sso?x=1",
    )
    res = _client().get("/saml/login", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("https://idp.example.com/sso")


def test_metadata_503_without_pysaml2(_enabled, monkeypatch):
    def _boom(*a, **k):
        raise saml_mod.SamlUnavailable("needs pysaml2")

    monkeypatch.setattr(saml_mod, "sp_metadata_xml", _boom)
    assert _client().get("/saml/metadata").status_code == 503


def test_acs_rejects_oversized_body_before_form_parse(_enabled, monkeypatch):
    def _should_not_verify(_r):
        raise AssertionError("oversized ACS body reached SAML verification")

    monkeypatch.setattr(saml_mod, "verify_acs_response", _should_not_verify)
    res = _client().post(
        "/saml/acs",
        data={"SAMLResponse": "x", "RelayState": "/" + ("a" * (1024 * 1024))},
        follow_redirects=False,
    )
    assert res.status_code == 413


def test_acs_rejects_oversized_saml_response_before_verification(_enabled, monkeypatch):
    def _should_not_verify(_r):
        raise AssertionError("oversized SAMLResponse reached SAML verification")

    monkeypatch.setattr(saml_mod, "verify_acs_response", _should_not_verify)
    res = _client().post(
        "/saml/acs",
        data={"SAMLResponse": "x" * (768 * 1024 + 1)},
        follow_redirects=False,
    )
    assert res.status_code == 413


# --- SCIM deprovision reach (persistent NameID) -----------------------------


def test_acs_records_persistent_nameid_for_scim_revocation(_enabled, monkeypatch, tmp_path):
    """A persistent/transient NameID matches no SCIM attribute, so SCIM
    deprovision can only reach the live SAML session if the ACS recorded the
    NameID against the user's email/UPN in the subject directory. Without that
    recording, ``subs_for([email])`` is empty and the session survives."""
    from maverick_dashboard import subject_directory as sd

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))

    name_id = "_persistent-okta-abc123"  # not an email; absent from SCIM attrs
    monkeypatch.setattr(
        saml_mod,
        "verify_acs_response",
        lambda r: saml_mod.SamlIdentity(
            name_id=name_id, attributes={"email": ["alice@example.com"]}
        ),
    )

    res = _client().post(
        "/saml/acs", data={"SAMLResponse": "signed"}, follow_redirects=False
    )
    assert res.status_code == 303

    # SCIM deprovision looks the sub up by the user's stable identifiers; the
    # persistent NameID must now be reachable via the email attribute.
    assert name_id in sd.subs_for(["alice@example.com"])
    assert name_id in sd.subs_for([name_id])


def test_record_session_subject_skips_when_no_email_attr(_enabled, monkeypatch, tmp_path):
    """With no email/UPN attribute the NameID is still recorded under itself
    (covers an email-format NameID that IS the SCIM identifier)."""
    from maverick_dashboard import subject_directory as sd

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))

    ident = saml_mod.SamlIdentity(name_id="bob@example.com", attributes={})
    saml_mod._record_session_subject(ident)
    assert "bob@example.com" in sd.subs_for(["bob@example.com"])
