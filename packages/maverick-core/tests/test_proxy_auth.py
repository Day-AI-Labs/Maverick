"""Reverse-proxy SSO: honor a forwarded identity header only from a trusted peer.

The security-critical bit is :func:`proxy_trusts` -- a forwarded header is
spoofable by a direct client, so it must be accepted only when the request's
network peer is the trusted upstream.
"""
from __future__ import annotations

from maverick.proxy_auth import (
    principal_from_proxy,
    proxy_auth_enabled,
    proxy_header_name,
    proxy_trusts,
)


def _cfg(monkeypatch, cfg):
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: cfg)


def test_disabled_by_default(monkeypatch):
    _cfg(monkeypatch, {})
    monkeypatch.delenv("MAVERICK_PROXY_AUTH", raising=False)
    assert proxy_auth_enabled() is False


def test_enabled_via_config(monkeypatch):
    monkeypatch.delenv("MAVERICK_PROXY_AUTH", raising=False)
    _cfg(monkeypatch, {"auth": {"proxy": {"enabled": True}}})
    assert proxy_auth_enabled() is True


def test_enabled_via_env(monkeypatch):
    _cfg(monkeypatch, {})
    monkeypatch.setenv("MAVERICK_PROXY_AUTH", "1")
    assert proxy_auth_enabled() is True


def test_header_default_and_override(monkeypatch):
    monkeypatch.delenv("MAVERICK_PROXY_AUTH_HEADER", raising=False)
    _cfg(monkeypatch, {})
    assert proxy_header_name() == "X-Forwarded-User"
    _cfg(monkeypatch, {"auth": {"proxy": {"header": "X-Auth-Request-Email"}}})
    assert proxy_header_name() == "X-Auth-Request-Email"


def test_trusts_loopback_by_default(monkeypatch):
    _cfg(monkeypatch, {})
    assert proxy_trusts("127.0.0.1") is True
    assert proxy_trusts("::1") is True
    assert proxy_trusts("10.0.0.9") is False   # a remote peer is not trusted
    assert proxy_trusts("") is False           # unknown peer fails closed
    assert proxy_trusts(None) is False


def test_trusts_configured_proxies_replace_default(monkeypatch):
    _cfg(monkeypatch, {"auth": {"proxy": {"trusted_proxies": ["10.0.0.5"]}}})
    assert proxy_trusts("10.0.0.5") is True
    # An explicit list is exact: it replaces the loopback default so a stray
    # local process can't assert identity unless you listed loopback too.
    assert proxy_trusts("127.0.0.1") is False


def test_principal_from_proxy_maps_to_user():
    p = principal_from_proxy("alice@example.com")
    assert p.principal == "user:alice@example.com"
    assert p.claims.get("via") == "proxy"
