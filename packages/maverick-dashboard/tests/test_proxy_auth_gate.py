"""Reverse-proxy SSO wiring in the dashboard's ``require_principal``.

Hermetic: we monkeypatch the ``maverick.proxy_auth`` seams bound into
``maverick_dashboard.auth`` and drive ``require_principal`` with a fake request,
so the tests exercise the dependency wiring (trusted-peer gate -> principal),
not config/IO.
"""
from __future__ import annotations

from types import SimpleNamespace

import maverick_dashboard.auth as auth


def _req(headers=None, host="127.0.0.1", path="/metrics"):
    return SimpleNamespace(
        headers=headers or {},
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host=host),
        state=SimpleNamespace(),
    )


def test_trusted_proxy_header_sets_principal(monkeypatch):
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "proxy_trusts", lambda host: host == "127.0.0.1")
    monkeypatch.setattr(auth, "proxy_header_name", lambda: "X-Forwarded-User")
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)  # proxy is the source

    req = _req(headers={"X-Forwarded-User": "alice"}, host="127.0.0.1")
    p = auth.require_principal(req)
    assert p is not None and p.principal == "user:alice"
    assert req.state.principal.principal == "user:alice"


def test_untrusted_peer_header_ignored(monkeypatch):
    # Header present but the peer is not the trusted proxy -> ignored. With OIDC
    # off this falls through to None: a direct client cannot spoof identity.
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "proxy_trusts", lambda host: False)
    monkeypatch.setattr(auth, "proxy_header_name", lambda: "X-Forwarded-User")
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)

    req = _req(headers={"X-Forwarded-User": "attacker"}, host="10.9.9.9")
    assert auth.require_principal(req) is None


def test_trusted_peer_without_header_falls_through(monkeypatch):
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "proxy_trusts", lambda host: True)
    monkeypatch.setattr(auth, "proxy_header_name", lambda: "X-Forwarded-User")
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)

    assert auth.require_principal(_req(headers={}, host="127.0.0.1")) is None


def test_proxy_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: False)
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    req = _req(headers={"X-Forwarded-User": "alice"})
    assert auth.require_principal(req) is None
