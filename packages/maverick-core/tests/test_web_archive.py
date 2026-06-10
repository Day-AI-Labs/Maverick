"""Web archive tool: save -> list -> get roundtrip, SSRF refusal, size cap.

Offline: ``httpx`` is faked in ``sys.modules`` (the lazy import + error types)
and the pinned ``_ssrf.safe_client`` transport is replaced with a scripted
client — the same seam the http_fetch streaming tests use. The SSRF test uses
a 169.254.* literal through the REAL guard, which needs no network.
"""
from __future__ import annotations

import json
import re
import sys
import types

import pytest
from maverick.tools import _ssrf
from maverick.tools.web_archive import MAX_BYTES, web_archive

URL = "https://example.com/article"


def _fake_httpx(monkeypatch):
    mod = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    mod.HTTPError = HTTPError
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


class _FakeResp:
    def __init__(self, status=200, headers=None, chunks=(b"<html>hi</html>",)):
        self.status_code = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self._chunks = list(chunks)

    def iter_bytes(self):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeClient:
    """Stands in for the pinned _ssrf.safe_client context manager."""

    def __init__(self, resp, seen):
        self._resp = resp
        self._seen = seen

    def stream(self, method, url, headers=None):
        self._seen.append((method, url))
        return self._resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_transport(monkeypatch, responses):
    """safe_client returns the next scripted response per hop."""
    _fake_httpx(monkeypatch)
    seen: list = []
    queue = list(responses)
    monkeypatch.setattr(
        _ssrf, "safe_client", lambda url, **kw: _FakeClient(queue.pop(0), seen))
    return seen


def test_save_list_get_roundtrip(tmp_path, monkeypatch):
    seen = _patch_transport(monkeypatch, [_FakeResp(chunks=(b"<html>", b"hello</html>"))])
    tool = web_archive(root=tmp_path / "wa")

    out = tool.fn({"op": "save", "url": URL, "note": "for the report"})
    assert "archived" in out
    aid = re.search(r"archived ([0-9a-f]{16})", out).group(1)
    assert seen == [("GET", URL)]

    adir = tmp_path / "wa" / aid
    assert (adir / "content.html").read_bytes() == b"<html>hello</html>"
    meta = json.loads((adir / "meta.json").read_text())
    assert meta["url"] == URL and meta["final_url"] == URL
    assert meta["status"] == 200
    assert meta["content_type"].startswith("text/html")
    assert meta["note"] == "for the report"
    assert len(meta["sha256"]) == 64
    assert meta["fetched_at"]

    listed = tool.fn({"op": "list"})
    assert aid in listed and URL in listed and "[200]" in listed
    assert "no archived" in tool.fn({"op": "list", "url_filter": "other-site"})
    assert URL in tool.fn({"op": "list", "url_filter": "example.com"})

    got = tool.fn({"op": "get", "id": aid})
    assert URL in got and "hello" in got and "sha256" in got


def test_save_same_url_same_day_reuses_one_snapshot(tmp_path, monkeypatch):
    _patch_transport(monkeypatch, [_FakeResp(), _FakeResp(chunks=(b"v2",))])
    tool = web_archive(root=tmp_path / "wa")
    a1 = re.search(r"archived ([0-9a-f]{16})", tool.fn({"op": "save", "url": URL})).group(1)
    a2 = re.search(r"archived ([0-9a-f]{16})", tool.fn({"op": "save", "url": URL})).group(1)
    assert a1 == a2
    assert len(list((tmp_path / "wa").iterdir())) == 1
    assert ((tmp_path / "wa") / a1 / "content.html").read_bytes() == b"v2"


def test_redirects_followed_with_final_url_recorded(tmp_path, monkeypatch):
    hop1 = _FakeResp(status=302, headers={"location": "https://example.com/moved"},
                     chunks=())
    hop2 = _FakeResp(chunks=(b"landed",))
    seen = _patch_transport(monkeypatch, [hop1, hop2])
    tool = web_archive(root=tmp_path / "wa")

    out = tool.fn({"op": "save", "url": URL})
    aid = re.search(r"archived ([0-9a-f]{16})", out).group(1)
    assert [u for _m, u in seen] == [URL, "https://example.com/moved"]
    meta = json.loads((tmp_path / "wa" / aid / "meta.json").read_text())
    assert meta["url"] == URL
    assert meta["final_url"] == "https://example.com/moved"


def test_ssrf_blocked_url_returns_error(tmp_path, monkeypatch):
    # Real _ssrf guard, no transport patch: a link-local literal (the cloud
    # metadata range) must be refused before any connection is attempted.
    _fake_httpx(monkeypatch)
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    tool = web_archive(root=tmp_path / "wa")
    out = tool.fn({"op": "save", "url": "http://169.254.169.254/latest/meta-data/"})
    assert out.startswith("ERROR")
    assert "refusing" in out
    assert not (tmp_path / "wa").exists()  # nothing stored


def test_size_cap_rejects_oversized_body(tmp_path, monkeypatch):
    big = [b"x" * (1024 * 1024)] * 6  # 6 MiB > 5 MiB cap
    _patch_transport(monkeypatch, [_FakeResp(chunks=big)])
    tool = web_archive(root=tmp_path / "wa")
    out = tool.fn({"op": "save", "url": URL})
    assert out.startswith("ERROR") and "5 MiB" in out
    assert not (tmp_path / "wa").exists()  # rejected, not truncated
    assert MAX_BYTES == 5 * 1024 * 1024


def test_bad_status_is_archived_and_recorded(tmp_path, monkeypatch):
    _patch_transport(monkeypatch, [_FakeResp(status=404, chunks=(b"gone",))])
    tool = web_archive(root=tmp_path / "wa")
    out = tool.fn({"op": "save", "url": URL})
    assert "archived" in out and "404" in out
    aid = re.search(r"archived ([0-9a-f]{16})", out).group(1)
    meta = json.loads((tmp_path / "wa" / aid / "meta.json").read_text())
    assert meta["status"] == 404
    assert "[404]" in tool.fn({"op": "list"})


def test_get_validates_id_shape(tmp_path):
    tool = web_archive(root=tmp_path / "wa")
    for evil in ("../secrets", "abc", "ABCDEF0123456789Z"):
        out = tool.fn({"op": "get", "id": evil})
        assert out.startswith("ERROR")
    assert "not found" in tool.fn({"op": "get", "id": "0" * 16})


def test_bad_scheme_and_missing_url(tmp_path, monkeypatch):
    _fake_httpx(monkeypatch)
    tool = web_archive(root=tmp_path / "wa")
    assert tool.fn({"op": "save", "url": "file:///etc/passwd"}).startswith("ERROR")
    assert tool.fn({"op": "save"}).startswith("ERROR")
    assert tool.fn({"op": "nope"}).startswith("ERROR")
    assert tool.fn({}).startswith("ERROR")


def test_tool_shape(tmp_path):
    tool = web_archive(root=tmp_path)
    assert tool.name == "web_archive"
    assert tool.parallel_safe is False  # it writes the data dir
    assert set(tool.input_schema["properties"]["op"]["enum"]) == {"save", "list", "get"}


@pytest.fixture(autouse=True)
def _no_private_override(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
