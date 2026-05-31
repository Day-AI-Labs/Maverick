"""SSRF consolidation: skill install and catalog fetch now go through the
same ``guarded_urlopen`` host check the http_fetch tool already uses, so a
user/model-supplied URL can't be pointed at a private/loopback/metadata
address. Loopback literals resolve without DNS, so these stay hermetic.
"""
from __future__ import annotations

import urllib.request

import pytest


def test_guarded_urlopen_blocks_loopback():
    from maverick.tools.http_fetch import guarded_urlopen
    with pytest.raises(ValueError) as ei:
        guarded_urlopen("https://127.0.0.1/x", timeout=1)
    assert "SSRF" in str(ei.value) or "private/loopback" in str(ei.value)


def test_guarded_urlopen_rejects_non_https_scheme():
    from maverick.tools.http_fetch import guarded_urlopen
    with pytest.raises(ValueError) as ei:
        guarded_urlopen("http://example.com/x", timeout=1)
    assert "http" in str(ei.value).lower()
    with pytest.raises(ValueError):
        guarded_urlopen("ftp://example.com/x", timeout=1)


def test_guarded_urlopen_allow_http_still_blocks_private():
    """allow_http=True relaxes only the scheme gate, not the SSRF host gate."""
    from maverick.tools.http_fetch import guarded_urlopen
    with pytest.raises(ValueError) as ei:
        guarded_urlopen("http://127.0.0.1/x", timeout=1, allow_http=True)
    # The SSRF message, not the "insecure http" one -> scheme gate passed.
    assert "private/loopback" in str(ei.value)


def test_guarded_urlopen_allows_public_host(monkeypatch):
    from maverick.tools import http_fetch

    seen = {}

    def _fake_urlopen(url, timeout=None):
        seen["url"] = url
        return object()

    monkeypatch.setattr(http_fetch, "is_blocked_host", lambda _h: False)
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    out = http_fetch.guarded_urlopen("https://example.com/data", timeout=5)
    assert out is not None
    assert seen["url"] == "https://example.com/data"


def test_skill_fetch_url_refuses_private_host():
    from maverick.skills import _fetch_url
    with pytest.raises(ValueError):
        _fetch_url("https://127.0.0.1/SKILL.md")


def test_catalog_index_blocked_host_degrades_to_none(tmp_path, monkeypatch):
    from maverick import catalog
    # Keep any cache lookups/writes off the real ~/.maverick dir.
    monkeypatch.setattr(catalog, "_cache_path", lambda url: tmp_path / "idx.json")
    # A loopback index URL is refused by the guard; the fetch degrades to
    # None (no entries) rather than raising.
    assert catalog._fetch_index_raw("https://127.0.0.1/catalog") is None
