"""SSRF-safe fetch: resolve-once + connection pinning (DNS-rebind defense)."""
from __future__ import annotations

import socket

import pytest
from maverick.tools import _ssrf


def _fake_getaddrinfo(*ips):
    def _inner(host, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    return _inner


def test_resolve_pinned_ip_returns_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert _ssrf.resolve_pinned_ip("example.com") == "93.184.216.34"


def test_resolve_pinned_ip_rejects_loopback(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    with pytest.raises(_ssrf.BlockedHost):
        _ssrf.resolve_pinned_ip("evil.test")


def test_resolve_pinned_ip_rejects_metadata_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(_ssrf.BlockedHost):
        _ssrf.resolve_pinned_ip("metadata.test")


def test_resolve_pinned_ip_rejects_mixed_records(monkeypatch):
    # A rebinding resolver returning one public + one private record must be
    # refused outright -- we can't trust any of the answers.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "127.0.0.1"))
    with pytest.raises(_ssrf.BlockedHost):
        _ssrf.resolve_pinned_ip("rebind.test")


def test_resolve_pinned_ip_unresolvable(monkeypatch):
    def _boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(_ssrf.BlockedHost):
        _ssrf.resolve_pinned_ip("does-not-exist.test")


def test_allow_private_override(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    # With the override the loopback IP is returned (and still pinned).
    assert _ssrf.resolve_pinned_ip("localhost") == "127.0.0.1"


def test_safe_client_rejects_bad_scheme():
    with pytest.raises(_ssrf.BlockedHost):
        _ssrf.safe_client("file:///etc/passwd")


def test_pinned_transport_rewrites_to_ip_and_preserves_host():
    """The transport must connect to the validated IP while keeping the Host
    header + TLS SNI bound to the original hostname."""
    import httpx

    captured = {}

    class _Inner:
        def handle_request(self, request):
            captured["host"] = request.url.host
            captured["sni"] = request.extensions.get("sni_hostname")
            captured["host_header"] = request.headers.get("Host")
            return httpx.Response(200, text="ok")

    t = _ssrf._PinnedTransport("example.com", "example.com", "93.184.216.34", _Inner())
    req = httpx.Request("GET", "https://example.com/path")
    resp = t.handle_request(req)

    assert resp.status_code == 200
    assert captured["host"] == "93.184.216.34"          # connects to the IP
    assert captured["sni"] == "example.com"             # TLS SNI = real host
    assert captured["host_header"] == "example.com"     # Host header = real host


def test_safe_client_builds_pinned_client(monkeypatch):
    import httpx

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    client = _ssrf.safe_client("https://example.com/x", timeout=5.0)
    assert isinstance(client, httpx.Client)
    assert isinstance(client._transport, _ssrf._PinnedTransport)
    client.close()


def test_safe_get_strips_follow_redirects(monkeypatch):
    # A caller passing follow_redirects=True must NOT be able to re-enable
    # redirect following on the pinned client: a 3xx would escape to an
    # unvalidated/unpinned host, which is the exact SSRF safe_get prevents.
    seen: dict = {}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kwargs):
            seen["kwargs"] = kwargs
            return "resp"

    monkeypatch.setattr(_ssrf, "safe_client", lambda url, **kw: _FakeClient())
    out = _ssrf.safe_get("https://example.com/x", follow_redirects=True, params={"a": 1})
    assert out == "resp"
    assert "follow_redirects" not in seen["kwargs"]
    # Genuine request kwargs are still forwarded untouched.
    assert seen["kwargs"].get("params") == {"a": 1}
