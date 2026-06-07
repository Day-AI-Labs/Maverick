"""http_fetch resolve-once-pin (DNS-rebind protection) + the robots fetch going
through the SSRF-safe, IP-pinned client."""
from __future__ import annotations

import pytest


def test_resolve_pinned_rejects_a_private_resolving_host(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    from maverick.tools.http_fetch import _resolve_pinned
    # localhost resolves to a loopback IP -> refused, and no pin is handed to the
    # connection layer, so it can't re-resolve to an internal address.
    with pytest.raises(ValueError):
        _resolve_pinned("localhost")


def test_resolve_pinned_honors_allow_private(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools.http_fetch import _resolve_pinned
    assert _resolve_pinned("localhost") == "localhost"   # override: no pinning


def test_check_robots_uses_the_ssrf_safe_client(monkeypatch):
    import maverick.tools._ssrf as ssrf
    seen = {}

    class _Resp:
        status_code = 200
        text = "User-agent: *\nDisallow:"

    def _fake_safe_get(url, **kwargs):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(ssrf, "safe_get", _fake_safe_get)
    from maverick.tools.http_fetch import _check_robots
    assert _check_robots("https://example.com/page") is True
    assert seen["url"].endswith("/robots.txt")          # fetched via safe_get, pinned
