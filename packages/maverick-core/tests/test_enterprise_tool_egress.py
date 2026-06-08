"""Enterprise mode locks *tool* egress (http_fetch / web_search), not just LLM calls."""
from __future__ import annotations

import pytest
from maverick.enterprise import egress_permitted, enterprise_egress_denial


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})


def _enterprise(monkeypatch, allowed=None):
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    if allowed is not None:
        monkeypatch.setattr(
            "maverick.config.load_config",
            lambda *a, **k: {"enterprise": {"allowed_hosts": allowed}},
        )


def test_egress_permitted_when_enterprise_off():
    assert egress_permitted("https://anywhere.example.com/x") is True
    assert enterprise_egress_denial("https://anywhere.example.com/x") is None


def test_public_host_denied_under_enterprise(monkeypatch):
    _enterprise(monkeypatch)
    assert egress_permitted("https://exfil.example.com/x") is False
    deny = enterprise_egress_denial("https://exfil.example.com/x", tool="http_fetch")
    assert deny and "exfil.example.com" in deny and "allowed_hosts" in deny


def test_local_endpoint_permitted_under_enterprise(monkeypatch):
    _enterprise(monkeypatch)
    assert egress_permitted("http://localhost:8080/x") is True
    assert egress_permitted("http://127.0.0.1/x") is True
    assert enterprise_egress_denial("http://localhost:8080/x") is None


def test_allow_listed_host_permitted_under_enterprise(monkeypatch):
    _enterprise(monkeypatch, allowed=["api.tavily.com"])
    assert egress_permitted("https://api.tavily.com/search") is True
    assert egress_permitted("https://other.example.com/x") is False


def test_http_fetch_blocks_egress_under_enterprise(monkeypatch):
    _enterprise(monkeypatch)
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")   # skip DNS, isolate the gate
    from maverick.tools.http_fetch import _run_fetch
    out = _run_fetch({"url": "https://exfil.invalid/steal"})
    assert out.startswith("ERROR:") and "enterprise mode" in out and "boundary" in out


def test_http_fetch_enterprise_denial_happens_before_robots(monkeypatch):
    _enterprise(monkeypatch)
    monkeypatch.setenv("MAVERICK_FETCH_RESPECT_ROBOTS", "1")
    from maverick.tools import http_fetch

    def fail_if_called(_url):
        raise AssertionError("robots.txt was checked before enterprise denial")

    monkeypatch.setattr(http_fetch, "_check_robots", fail_if_called)
    out = http_fetch._run_fetch({"url": "https://exfil.invalid/steal"})
    assert out.startswith("ERROR:") and "enterprise mode" in out and "boundary" in out


def test_web_search_disabled_under_enterprise_without_allowlist(monkeypatch):
    _enterprise(monkeypatch)
    from maverick.tools.web_search import _run_search
    out = _run_search({"query": "sensitive patient data"})
    assert "disabled in enterprise mode" in out


def test_web_search_allows_an_allow_listed_backend(monkeypatch):
    # Allow-listing tavily lets it past the gate (it then fails on no API key, not on
    # the enterprise gate -- proving the gate permitted it rather than blocking all).
    _enterprise(monkeypatch, allowed=["api.tavily.com"])
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from maverick.tools.web_search import _run_search
    out = _run_search({"query": "x"})
    assert "disabled in enterprise mode" not in out
