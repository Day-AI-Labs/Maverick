"""Generic REST connector factory + the enterprise-connector spec batch.

Network-free: ``httpx`` is faked. Covers auth modes, the confirm gate, request
routing, and that every spec'd connector registers.
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


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    r.text = str(body)
    return r


def _tool(**kw):
    from maverick.tools._rest_connector import make_rest_tool
    spec = dict(name="acme", base_url_env="ACME_BASE_URL", token_env="ACME_TOKEN",
                description="Acme test connector")
    spec.update(kw)
    return make_rest_tool(**spec)


def _set(monkeypatch):
    monkeypatch.setenv("ACME_BASE_URL", "https://acme.example.com")
    monkeypatch.setenv("ACME_TOKEN", "tok123")


def test_requires_config(monkeypatch):
    monkeypatch.delenv("ACME_BASE_URL", raising=False)
    monkeypatch.delenv("ACME_TOKEN", raising=False)
    _fake_httpx(monkeypatch, request=MagicMock())
    out = _tool().fn({"op": "get", "path": "/things"})
    assert "ERROR" in out and "ACME_BASE_URL" in out


def test_get_routes_and_returns_json(monkeypatch):
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(200, {"items": [{"id": 1}]}))
    _fake_httpx(monkeypatch, request=req)
    out = _tool().fn({"op": "get", "path": "/things", "params": {"q": "x"}})
    assert "items" in out
    assert req.call_args.args[0] == "GET"
    assert req.call_args.args[1] == "https://acme.example.com/things"


def test_write_needs_confirm(monkeypatch):
    _set(monkeypatch)
    req = MagicMock()
    _fake_httpx(monkeypatch, request=req)
    out = _tool().fn({"op": "post", "path": "/things", "body": {"a": 1}})
    assert "DRY RUN" in out
    req.assert_not_called()


def test_write_with_confirm_executes(monkeypatch):
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(201, {"ok": True}))
    _fake_httpx(monkeypatch, request=req)
    out = _tool().fn({"op": "post", "path": "/things", "body": {"a": 1}, "confirm": True})
    assert "ok" in out
    assert req.call_args.args[0] == "POST"


def test_bearer_auth_header(monkeypatch):
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(200, {}))
    _fake_httpx(monkeypatch, request=req)
    _tool().fn({"op": "get", "path": "/x"})
    assert req.call_args.kwargs["headers"]["Authorization"] == "Bearer tok123"


def test_basic_auth_header(monkeypatch):
    import base64
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(200, {}))
    _fake_httpx(monkeypatch, request=req)
    _tool(basic=True).fn({"op": "get", "path": "/x"})
    expected = "Basic " + base64.b64encode(b"tok123:x").decode()
    assert req.call_args.kwargs["headers"]["Authorization"] == expected


def test_scheme_override(monkeypatch):
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(200, {}))
    _fake_httpx(monkeypatch, request=req)
    _tool(scheme="SSWS").fn({"op": "get", "path": "/x"})
    assert req.call_args.kwargs["headers"]["Authorization"] == "SSWS tok123"


def test_custom_header_raw_token(monkeypatch):
    _set(monkeypatch)
    req = MagicMock(return_value=_resp(200, {}))
    _fake_httpx(monkeypatch, request=req)
    _tool(token_header="X-Tableau-Auth", scheme="").fn({"op": "get", "path": "/x"})
    assert req.call_args.kwargs["headers"]["X-Tableau-Auth"] == "tok123"


def test_all_enterprise_connectors_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry
    from maverick.tools.enterprise_connectors import ENTERPRISE_CONNECTOR_NAMES

    class _W:
        def open_questions(self, gid):
            return []

    names = {t.name for t in base_registry(_W(), LocalBackend(workdir=tmp_path)).all()}
    for n in ENTERPRISE_CONNECTOR_NAMES:
        assert n in names, n
    # sanity: the batch is non-trivial and unique
    assert len(ENTERPRISE_CONNECTOR_NAMES) == len(set(ENTERPRISE_CONNECTOR_NAMES))
    assert len(ENTERPRISE_CONNECTOR_NAMES) >= 15


def test_enterprise_connectors_are_high_risk():
    from maverick.safety.tool_risk import tool_risk, tools_exceeding
    from maverick.tools.enterprise_connectors import ENTERPRISE_CONNECTOR_NAMES

    assert all(tool_risk(n) == "high" for n in ENTERPRISE_CONNECTOR_NAMES)
    assert tools_exceeding(ENTERPRISE_CONNECTOR_NAMES, "medium") == set(ENTERPRISE_CONNECTOR_NAMES)


def _gql(**kw):
    from maverick.tools._rest_connector import make_graphql_tool
    spec = dict(name="acmegql", base_url_env="ACMEGQL_URL", token_env="ACMEGQL_TOKEN",
                description="Acme GraphQL")
    spec.update(kw)
    return make_graphql_tool(**spec)


def test_graphql_query_runs(monkeypatch):
    monkeypatch.setenv("ACMEGQL_URL", "https://gql.example.com")
    monkeypatch.setenv("ACMEGQL_TOKEN", "tok")
    post = MagicMock(return_value=_resp(200, {"data": {"me": {"id": 1}}}))
    _fake_httpx(monkeypatch, post=post)
    out = _gql().fn({"op": "query", "query": "query { me { id } }"})
    assert "me" in out
    assert post.call_args.args[0] == "https://gql.example.com"


def test_graphql_mutation_needs_confirm(monkeypatch):
    monkeypatch.setenv("ACMEGQL_URL", "https://gql.example.com")
    monkeypatch.setenv("ACMEGQL_TOKEN", "tok")
    post = MagicMock()
    _fake_httpx(monkeypatch, post=post)
    out = _gql().fn({"op": "query", "query": "mutation { delete_item(id: 1) { id } }"})
    assert "DRY RUN" in out
    post.assert_not_called()


def test_graphql_requires_config(monkeypatch):
    monkeypatch.delenv("ACMEGQL_URL", raising=False)
    monkeypatch.delenv("ACMEGQL_TOKEN", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    out = _gql().fn({"op": "query", "query": "query { x }"})
    assert "ERROR" in out and "ACMEGQL_URL" in out


def test_graphql_errors_field_is_error(monkeypatch):
    monkeypatch.setenv("ACMEGQL_URL", "https://gql.example.com")
    monkeypatch.setenv("ACMEGQL_TOKEN", "tok")
    post = MagicMock(return_value=_resp(200, {"errors": [{"message": "bad field"}]}))
    _fake_httpx(monkeypatch, post=post)
    out = _gql().fn({"op": "query", "query": "query { nope }"})
    assert out.startswith("ERROR") and "bad field" in out
