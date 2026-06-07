"""Integration tests for the built-in OIDC browser-login flow.

Hermetic: no real network and no real JWT. We configure the login flow via
``MAVERICK_OIDC_*`` env (so the real ``login_enabled()`` / ``load_oidc_config()``
gate is exercised), with explicit authorization/token endpoints so discovery is
never called. The token exchange (``httpx.post``) and the ID-token verification
(``maverick.oidc.verify_oidc_token``, imported into ``oidc_login``) are
monkeypatched.

Covers the security checklist: login redirects with state + PKCE S256; callback
happy path sets the session + redirects to a safe ``return_to``; state-mismatch
-> 400 (no token exchange); open-redirect blocked; logout clears; and all routes
404 when login is disabled.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import maverick_dashboard.oidc_login as ol
import pytest
from fastapi.testclient import TestClient
from maverick.oidc import VerifiedPrincipal
from maverick.web_session import verify_session
from maverick_dashboard.app import app

AUTH_ENDPOINT = "https://idp.example.com/authorize"
TOKEN_ENDPOINT = "https://idp.example.com/token"
SESSION_SECRET = "unit-test-session-secret"  # pragma: allowlist secret
CLIENT_ID = "test-client-id"
ISSUER = "https://idp.example.com"


@pytest.fixture
def login_env(monkeypatch, tmp_path):
    """Fully configure the login flow via env (explicit endpoints, no discovery)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_OIDC_ENABLED", "1")
    monkeypatch.setenv("MAVERICK_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("MAVERICK_OIDC_AUDIENCE", "maverick")
    monkeypatch.setenv("MAVERICK_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("MAVERICK_OIDC_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "MAVERICK_OIDC_REDIRECT_URI", "http://testserver/auth/callback"
    )
    monkeypatch.setenv("MAVERICK_OIDC_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("MAVERICK_OIDC_AUTHORIZATION_ENDPOINT", AUTH_ENDPOINT)
    monkeypatch.setenv("MAVERICK_OIDC_TOKEN_ENDPOINT", TOKEN_ENDPOINT)
    # No dashboard token: keep the dashboard-token middleware out of the way; the
    # /auth/* routes are exempt regardless, and gated routes still hit the OIDC
    # dependency.
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)


@pytest.fixture
def client():
    return TestClient(app)


# ---- login: redirect carries state + PKCE S256 --------------------------------


def test_login_redirects_with_state_and_pkce(login_env, client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(AUTH_ENDPOINT + "?")
    q = parse_qs(urlparse(location).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["scope"] == ["openid"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] and q["code_challenge"][0]
    assert q["state"] and q["state"][0]

    # The transaction cookie is set, httponly, samesite=lax, and signed.
    set_cookie = resp.headers["set-cookie"]
    assert ol.TX_COOKIE in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    tx_raw = client.cookies.get(ol.TX_COOKIE)
    tx = verify_session(tx_raw, SESSION_SECRET)
    assert tx is not None
    # The state in the cookie matches the state sent to the IdP.
    assert tx["state"] == q["state"][0]
    assert tx["cv"]  # PKCE code_verifier stashed server-side (in the cookie)


def test_login_sanitizes_open_redirect_return_to(login_env, client):
    """An external return_to is dropped to '/' before being stashed."""
    resp = client.get(
        "/auth/login?return_to=https://evil.example.com/x", follow_redirects=False
    )
    assert resp.status_code == 302
    tx = verify_session(client.cookies.get(ol.TX_COOKIE), SESSION_SECRET)
    assert tx["return_to"] == "/"


def test_login_keeps_safe_return_to(login_env, client):
    resp = client.get("/auth/login?return_to=/goals", follow_redirects=False)
    assert resp.status_code == 302
    tx = verify_session(client.cookies.get(ol.TX_COOKIE), SESSION_SECRET)
    assert tx["return_to"] == "/goals"


# ---- callback: happy path -----------------------------------------------------


def _do_login(client, return_to="/goals"):
    """Run /auth/login and return the (state, tx_cookie_value)."""
    path = "/auth/login" + (f"?return_to={return_to}" if return_to else "")
    resp = client.get(path, follow_redirects=False)
    location = resp.headers["location"]
    state = parse_qs(urlparse(location).query)["state"][0]
    return state, client.cookies.get(ol.TX_COOKIE)


def test_callback_happy_path_sets_session_and_redirects(login_env, client, monkeypatch):
    state, _ = _do_login(client, return_to="/goals")

    posted = {}

    class _TokenResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "fake.id.token", "access_token": "ignored"}

    def _fake_post(url, data=None, auth=None, timeout=None):
        posted["url"] = url
        posted["data"] = data
        posted["auth"] = auth
        return _TokenResp()

    monkeypatch.setattr(ol.httpx, "post", _fake_post)
    monkeypatch.setattr(
        ol, "verify_oidc_token",
        lambda token: VerifiedPrincipal(
            sub="user-xyz", issuer=ISSUER, audience="maverick",
            claims={"sub": "user-xyz"},
        ),
    )

    resp = client.get(
        f"/auth/callback?code=auth-code-abc&state={state}", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/goals"

    # PKCE verifier + the right grant were sent to the (https) token endpoint.
    assert posted["url"] == TOKEN_ENDPOINT
    assert posted["data"]["grant_type"] == "authorization_code"
    assert posted["data"]["code"] == "auth-code-abc"
    assert posted["data"]["code_verifier"]
    assert posted["auth"] == (CLIENT_ID, "test-client-secret")

    # Session cookie set + valid; tx cookie cleared.
    session_raw = client.cookies.get(ol.SESSION_COOKIE)
    assert session_raw
    payload = verify_session(session_raw, SESSION_SECRET)
    assert payload is not None and payload["sub"] == "user-xyz"
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie


def test_session_cookie_authenticates_gated_route(login_env, client, monkeypatch):
    """After login, the session cookie satisfies require_principal on a gated
    route (here /metrics), with OIDC enabled and no bearer header."""
    state, _ = _do_login(client)

    class _TokenResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "fake.id.token"}

    monkeypatch.setattr(ol.httpx, "post", lambda *a, **k: _TokenResp())
    monkeypatch.setattr(
        ol, "verify_oidc_token",
        lambda token: VerifiedPrincipal(
            sub="user-xyz", issuer=ISSUER, audience="maverick", claims={},
        ),
    )
    client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)

    # /metrics is gated by the OIDC dependency; the session cookie should let it
    # through with no Authorization header.
    resp = client.get("/metrics")
    assert resp.status_code == 200


# ---- callback: state mismatch (CSRF) ------------------------------------------


def test_callback_state_mismatch_returns_400_no_exchange(login_env, client, monkeypatch):
    _do_login(client)

    def _must_not_post(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("token exchange ran despite state mismatch")

    monkeypatch.setattr(ol.httpx, "post", _must_not_post)

    resp = client.get(
        "/auth/callback?code=c&state=WRONG-STATE", follow_redirects=False
    )
    assert resp.status_code == 400


def test_callback_missing_tx_cookie_fails(login_env, client, monkeypatch):
    """No transaction cookie at all -> failure, no token exchange."""
    def _must_not_post(*a, **k):  # pragma: no cover
        raise AssertionError("token exchange ran without a tx cookie")

    monkeypatch.setattr(ol.httpx, "post", _must_not_post)
    # Fresh client (no tx cookie).
    fresh = TestClient(app)
    resp = fresh.get("/auth/callback?code=c&state=whatever", follow_redirects=False)
    assert resp.status_code in (303, 400)  # redirect to /auth/error (cleared)
    # No session was set.
    assert not fresh.cookies.get(ol.SESSION_COOKIE)


# ---- callback: id_token verification failure ----------------------------------


def test_callback_verify_failure_sets_no_session(login_env, client, monkeypatch):
    from maverick.oidc import OIDCError

    state, _ = _do_login(client)

    class _TokenResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "bad.token"}

    monkeypatch.setattr(ol.httpx, "post", lambda *a, **k: _TokenResp())

    def _reject(token):
        raise OIDCError("verification failed")

    monkeypatch.setattr(ol, "verify_oidc_token", _reject)

    resp = client.get(
        f"/auth/callback?code=c&state={state}", follow_redirects=False
    )
    assert resp.status_code == 303  # redirect to error
    assert not client.cookies.get(ol.SESSION_COOKIE)


# ---- logout -------------------------------------------------------------------


def test_logout_clears_session(login_env, client):
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    set_cookie = resp.headers.get("set-cookie", "")
    # delete_cookie sets the cookie with an empty value / expiry in the past.
    assert ol.SESSION_COOKIE in set_cookie


# ---- disabled: every route 404s -----------------------------------------------


def test_routes_404_when_login_disabled(monkeypatch, tmp_path):
    """With the login flow not configured, all /auth/* routes 404 (inert)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (
        "MAVERICK_OIDC_ENABLED",
        "MAVERICK_OIDC_CLIENT_ID",
        "MAVERICK_OIDC_SESSION_SECRET",
        "MAVERICK_OIDC_ISSUER",
        "MAVERICK_OIDC_AUTHORIZATION_ENDPOINT",
        "MAVERICK_OIDC_TOKEN_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    c = TestClient(app)
    for path in ("/auth/login", "/auth/callback", "/auth/logout", "/auth/error"):
        assert c.get(path, follow_redirects=False).status_code == 404
