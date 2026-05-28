"""Council security pass — dashboard auth + CSRF + headers + skill-install gate."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


# ---------- bearer auth: query-token branch deleted ----------

def test_query_token_no_longer_accepted(monkeypatch, tmp_path):
    """`?token=...` used to leak via Referer/history/access logs. Killed."""
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "sekret")
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    client = _client()
    resp = client.get("/?token=sekret")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unauthorized"


def test_header_token_still_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "sekret")
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    client = _client()
    resp = client.get("/", headers={"Authorization": "Bearer sekret"})
    assert resp.status_code == 200


def test_unauth_request_blocked_when_token_set(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "sekret")
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 401


def test_healthz_still_exempt(monkeypatch):
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "sekret")
    client = _client()
    resp = client.get("/livez")
    assert resp.status_code == 200


# ---------- same-origin: fail-closed on missing headers ----------

def test_is_same_origin_fails_closed_on_post_without_headers(monkeypatch, tmp_path):
    """Prior fail-open let any same-machine tab POST to /chat/send via no-cors fetch."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    # No Origin, no Referer — the previous fail-open branch let this through.
    resp = client.post("/chat/send", data={"title": "x"})
    assert resp.status_code == 403
    assert "cross-site" in resp.json()["detail"]


def test_is_same_origin_accepts_with_matching_origin(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post(
        "/chat/send",
        data={"title": "x"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_safe_methods_skip_csrf(monkeypatch, tmp_path):
    """GET/HEAD/OPTIONS bypass the same-origin check — they don't mutate."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.get("/")  # No Origin, no Referer
    assert resp.status_code == 200


# ---------- same-origin now covers /api/v1 mutations (launch review) ----------

def test_api_v1_mutation_blocks_forged_origin(monkeypatch, tmp_path):
    """The /api/v1 mutating routes (cancel/resume/halt/disable/enable/purge,
    POST facts) skipped the same-origin check that /chat/send enforced. In
    no-token (loopback) mode a malicious page could disable safety tools, arm
    the killswitch, or purge caches via an ambient cross-site POST. Now gated
    centrally in bearer_auth."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post(
        "/api/v1/facts",
        json={"key": "x", "value": "y"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert "cross-site" in resp.json()["detail"]


def test_api_v1_mutation_blocks_missing_origin(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post("/api/v1/facts", json={"key": "x", "value": "y"})
    assert resp.status_code == 403


def test_api_v1_mutation_allows_matching_origin(monkeypatch, tmp_path):
    """A legitimate same-origin request passes the gate and reaches the handler."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post(
        "/api/v1/facts",
        json={"key": "city", "value": "Lisbon"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 204


# ---------- no-token mode refuses proxied requests (launch review) ----------

def test_no_token_proxied_request_requires_token(monkeypatch, tmp_path):
    """A reverse proxy on the same host connects over loopback, so trusting the
    loopback peer in no-token mode would serve the control surface
    unauthenticated behind a public proxy. Any forwarding header => require a
    token (fail closed)."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.get("/", headers={"X-Forwarded-For": "203.0.113.7"})
    assert resp.status_code == 401
    assert "MAVERICK_DASHBOARD_TOKEN" in resp.json()["detail"]


def test_no_token_proxied_via_forwarded_header_requires_token(monkeypatch, tmp_path):
    """The RFC 7239 ``Forwarded`` header is honored too, not just X-Forwarded-*."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.get("/", headers={"Forwarded": "for=203.0.113.7"})
    assert resp.status_code == 401


def test_no_token_direct_loopback_still_served(monkeypatch, tmp_path):
    """Direct local use (no proxy headers) is unaffected by the proxy guard."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200


# ---------- baseline security headers ----------

def test_security_headers_present_on_every_response(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.get("/")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cross-Origin-Opener-Policy"] == "same-origin"


# ---------- skill install gate ----------

def test_skill_install_blocked_by_default(monkeypatch, tmp_path):
    """POST /api/v1/skills was one-shot RCE for anyone past auth. Now opt-in."""
    monkeypatch.delenv("MAVERICK_ALLOW_SKILL_INSTALL", raising=False)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post(
        "/api/v1/skills",
        json={"source": "gh:attacker/skill"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 403
    assert "MAVERICK_ALLOW_SKILL_INSTALL" in resp.json()["detail"]


def test_skill_install_enabled_by_env(monkeypatch, tmp_path):
    """With the opt-in flag, the endpoint reaches install_skill (and fails on bad URL)."""
    monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    resp = client.post(
        "/api/v1/skills",
        json={"source": "gh:not/real/path/that/will/fail"},
        headers={"Origin": "http://testserver"},
    )
    # 400 = install_skill raised ValueError (bad URL); we're past the gate.
    assert resp.status_code in (400, 404, 500)
    assert resp.status_code != 403
