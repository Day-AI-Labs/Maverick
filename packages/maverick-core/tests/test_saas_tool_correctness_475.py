"""Issue #475 — SaaS tool API correctness.

Focused regression tests for the Datadog `monitors` name-filter fix: a name
filter must hit /api/v1/monitor/search with `query=name:...` (the plain
/api/v1/monitor endpoint has no `name` param and would silently return every
monitor), while an unfiltered list keeps using /api/v1/monitor.

The other #475 fixes (PagerDuty From header, ClickUp pagination, Confluence
space.key, Notion/GitLab pagination) are covered by their own suites. The Jira
/search -> /search/jql migration is deliberately skipped per the issue (needs
verification against the live API before changing request/response shape).
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _fake_httpx(monkeypatch, **methods):
    mod = types.ModuleType("httpx")
    for name, value in methods.items():
        setattr(mod, name, value)
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def _resp(status: int, body: object):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    r.text = str(body)
    return r


def test_datadog_monitors_name_filter_uses_search_endpoint(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    monkeypatch.setenv("DATADOG_APP_KEY", "a")
    body = {"monitors": [{"id": 7, "overall_state": "OK", "name": "cpu high"}]}
    get = MagicMock(return_value=_resp(200, body))
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.datadog_tool import datadog_tool

    out = datadog_tool().fn({"op": "monitors", "name": "cpu", "limit": 10})
    assert "cpu high" in out
    url = get.call_args.args[0]
    params = get.call_args.kwargs["params"]
    assert url.endswith("/api/v1/monitor/search")
    assert params["query"] == "name:cpu"


def test_datadog_monitors_no_name_uses_list_endpoint(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    monkeypatch.setenv("DATADOG_APP_KEY", "a")
    body = [{"id": 1, "overall_state": "Alert", "name": "disk full"}]
    get = MagicMock(return_value=_resp(200, body))
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.datadog_tool import datadog_tool

    out = datadog_tool().fn({"op": "monitors"})
    assert "disk full" in out
    assert get.call_args.args[0].endswith("/api/v1/monitor")


def test_datadog_monitors_search_no_matches(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    monkeypatch.setenv("DATADOG_APP_KEY", "a")
    get = MagicMock(return_value=_resp(200, {"monitors": []}))
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.datadog_tool import datadog_tool

    out = datadog_tool().fn({"op": "monitors", "name": "nope"})
    assert out == "no monitors"
