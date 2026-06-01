"""view_image must stream the HTTP body with a hard ceiling, not buffer the
whole thing before checking the 20 MiB cap.

Regression: the fetch used `safe_get`, which materializes `resp.content`
(the entire body) before the `len(...) > 20 MiB` check ran -- so a
model-supplied URL to a multi-GB resource was fully loaded into memory before
being rejected, defeating the cap. It now streams via `safe_client(...).stream`
with a content-length precheck and an incremental ceiling.
"""
from __future__ import annotations


class _FakeStreamResp:
    def __init__(self, chunks, headers):
        self._chunks = chunks
        self.headers = headers

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    def stream(self, method, url):
        return self._resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, resp):
    import maverick.tools._ssrf as ssrf
    monkeypatch.setattr(ssrf, "safe_client", lambda url, **k: _FakeClient(resp))


def test_view_image_caps_without_reading_whole_body(monkeypatch):
    from maverick.tools import view_image as vi
    consumed = {"chunks": 0}

    def chunks():
        for _ in range(100):  # 100 x 1 MiB available; cap is 20 MiB
            consumed["chunks"] += 1
            yield b"x" * (1024 * 1024)

    _patch(monkeypatch, _FakeStreamResp(chunks(), {"content-type": "image/png"}))
    assert vi._load_image("https://example.com/big.png") is None
    # Stopped shortly after crossing 20 MiB -- did NOT read all 100 chunks.
    assert consumed["chunks"] <= 22


def test_view_image_rejects_on_content_length_without_streaming(monkeypatch):
    from maverick.tools import view_image as vi
    pulled = {"n": 0}

    def chunks():
        pulled["n"] += 1
        yield b"x"

    headers = {"content-type": "image/png", "content-length": str(50 * 1024 * 1024)}
    _patch(monkeypatch, _FakeStreamResp(chunks(), headers))
    assert vi._load_image("https://example.com/huge.png") is None
    assert pulled["n"] == 0  # rejected on content-length, never streamed


def test_view_image_returns_bytes_and_mime_on_normal_body(monkeypatch):
    from maverick.tools import view_image as vi
    resp = _FakeStreamResp([b"\x89PNG", b"data"], {"content-type": "image/png"})
    _patch(monkeypatch, resp)
    out = vi._load_image("https://example.com/ok.png")
    assert out == (b"\x89PNGdata", "image/png")
