"""http_fetch download cap + SSRF redirect re-validation (#477)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------- streaming byte cap ----------

class _StreamResp:
    """Streaming-response mock: yields the body in small chunks so the
    consumer's max_bytes cap is what stops the read, not the body size."""

    def __init__(self, body: bytes, content_type="text/plain"):
        self._body = body
        self.status_code = 200
        self.reason_phrase = "OK"
        self.encoding = "utf-8"
        self.url = "http://localhost/"
        self.headers = {"content-type": content_type}
        self.iter_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        # 1 KiB chunks; record how many were consumed so the test can prove
        # we stopped early instead of reading the whole body.
        for i in range(0, len(self._body), 1024):
            self.iter_count += 1
            yield self._body[i:i + 1024]


class _StreamClient:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        return self._resp


def test_download_is_capped_at_max_bytes(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools import http_fetch as hf
    big = b"A" * (1024 * 1024)  # 1 MiB body
    resp = _StreamResp(big)
    import httpx
    with patch.object(httpx, "Client", lambda *a, **k: _StreamClient(resp)):
        out = hf.http_fetch().fn(
            {"url": "http://127.0.0.1/", "render": "raw", "max_bytes": 4096}
        )
    # The output reflects the cap, and the response is marked truncated.
    assert "truncated" in out
    # We stopped consuming chunks well before the full 1 MiB (1024 chunks);
    # ~5 chunks is enough to exceed a 4096-byte cap.
    assert resp.iter_count < 20


def test_small_body_not_truncated(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools import http_fetch as hf
    resp = _StreamResp(b"hello world")
    import httpx
    with patch.object(httpx, "Client", lambda *a, **k: _StreamClient(resp)):
        out = hf.http_fetch().fn(
            {"url": "http://127.0.0.1/", "render": "raw", "max_bytes": 200_000}
        )
    assert "hello world" in out
    assert "truncated" not in out


# ---------- SSRF redirect re-validation ----------

def test_redirect_to_private_host_refused(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    import urllib.error

    from maverick.tools.http_fetch import ssrf_redirect_handler
    h = ssrf_redirect_handler()
    # A redirect Location pointing at the cloud metadata endpoint must raise.
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(
            req=None, fp=None, code=302, msg="Found", headers={},
            newurl="http://169.254.169.254/latest/meta-data/",
        )


def test_redirect_to_loopback_refused(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    import urllib.error

    from maverick.tools.http_fetch import ssrf_redirect_handler
    h = ssrf_redirect_handler()
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(
            req=None, fp=None, code=301, msg="Moved", headers={},
            newurl="http://127.0.0.1:8080/admin",
        )


def test_redirect_to_nonhttp_scheme_refused():
    import urllib.error

    from maverick.tools.http_fetch import ssrf_redirect_handler
    h = ssrf_redirect_handler()
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(
            req=None, fp=None, code=302, msg="Found", headers={},
            newurl="file:///etc/passwd",
        )


def test_private_redirect_allowed_with_override(monkeypatch):
    # The escape hatch applies to redirects too: with the override on, a
    # private redirect is permitted (the handler defers to super()).
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools.http_fetch import ssrf_redirect_handler
    h = ssrf_redirect_handler()
    # super().redirect_request builds a Request for a normal 30x; it should
    # NOT raise our SSRF HTTPError. (It may return a Request or None.)
    import urllib.request
    req = urllib.request.Request("https://example.com/")
    result = h.redirect_request(
        req=req, fp=None, code=302, msg="Found", headers={},
        newurl="http://10.0.0.5/internal",
    )
    # No exception => allowed; result is a Request (or None if urllib
    # declined for another reason, but it must not be our SSRF error).
    assert result is None or isinstance(result, urllib.request.Request)


def test_ssrf_safe_opener_builds():
    from maverick.tools.http_fetch import ssrf_safe_opener
    import urllib.request
    opener = ssrf_safe_opener()
    assert isinstance(opener, urllib.request.OpenerDirector)
