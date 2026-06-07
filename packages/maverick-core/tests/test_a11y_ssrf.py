"""a11y `check` must refuse file:// and private/metadata URLs (LFI / SSRF):
pa11y and axe drive a real headless browser, so the target URL is attacker-
reachable just like an http_fetch."""
from __future__ import annotations

from maverick.tools.a11y import _check_url, a11y


def test_rejects_file_scheme():
    out = _check_url("file:///etc/passwd")
    assert out is not None and "http(s)" in out


def test_rejects_non_http_scheme():
    assert _check_url("ftp://example.com/x") is not None


def test_rejects_loopback_host():
    assert _check_url("http://127.0.0.1/") is not None


def test_rejects_metadata_ip():
    assert _check_url("http://169.254.169.254/latest/meta-data/") is not None


def test_allow_private_override_permits_loopback(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    assert _check_url("http://127.0.0.1/") is None


def test_check_op_blocks_file_url_before_runner():
    # The URL guard runs BEFORE _ensure_runner, so a file:// target is refused
    # with the SSRF error even when no pa11y/axe binary is installed.
    out = a11y().fn({"op": "check", "url": "file:///etc/passwd"})
    assert out.startswith("ERROR") and "http(s)" in out


def test_check_html_path_still_allowed_without_url_guard(monkeypatch):
    # check_html takes a confined local path, not a URL -- the url guard must
    # not interfere with it. With no sandbox and no binary, we just get the
    # runner-missing error (not an SSRF rejection).
    out = a11y().fn({"op": "check_html", "path": "report.html"})
    assert out.startswith("ERROR")
    assert "http(s)" not in out
