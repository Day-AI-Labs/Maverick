"""Strategic-fit connectors: ServiceNow, Snowflake, Databricks, OneTrust, Vertex.

Network-free: ``httpx`` is faked so we exercise registration, auth-config
errors, the confirm gate, request routing, and response shaping with no real
API call.
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


# --------------------------- registration smoke ---------------------------

def test_connectors_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    names = {t.name for t in base_registry(_W(), LocalBackend(workdir=tmp_path)).all()}
    for n in ("servicenow", "snowflake", "databricks", "onetrust", "vertex"):
        assert n in names, n


# --------------------------------- ServiceNow ------------------------------

def test_servicenow_requires_config(monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    monkeypatch.delenv("SERVICENOW_TOKEN", raising=False)
    _fake_httpx(monkeypatch, request=MagicMock())
    from maverick.tools.servicenow_tool import servicenow_tool
    out = servicenow_tool().fn({"op": "query", "table": "incident"})
    assert "ERROR" in out and "SERVICENOW" in out


def test_servicenow_query_hits_table_api(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://x.service-now.com")
    monkeypatch.setenv("SERVICENOW_TOKEN", "t")
    req = MagicMock(return_value=_resp(200, {"result": [{"number": "INC001"}]}))
    _fake_httpx(monkeypatch, request=req)
    from maverick.tools.servicenow_tool import servicenow_tool
    out = servicenow_tool().fn({"op": "query", "table": "incident", "query": "active=true"})
    assert "INC001" in out
    assert req.call_args.args[0] == "GET"
    assert req.call_args.args[1].endswith("/api/now/table/incident")


def test_servicenow_create_needs_confirm(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://x.service-now.com")
    monkeypatch.setenv("SERVICENOW_TOKEN", "t")
    req = MagicMock()
    _fake_httpx(monkeypatch, request=req)
    from maverick.tools.servicenow_tool import servicenow_tool
    out = servicenow_tool().fn({"op": "create", "table": "incident",
                                "fields": {"short_description": "x"}})
    assert "DRY RUN" in out
    req.assert_not_called()


# ---------------------------------- Snowflake ------------------------------

def test_snowflake_requires_config(monkeypatch):
    monkeypatch.delenv("SNOWFLAKE_ACCOUNT", raising=False)
    monkeypatch.delenv("SNOWFLAKE_TOKEN", raising=False)
    _fake_httpx(monkeypatch)
    from maverick.tools.snowflake_tool import snowflake_tool
    out = snowflake_tool().fn({"op": "query", "statement": "select 1"})
    assert "ERROR" in out and "SNOWFLAKE" in out


def test_snowflake_select_runs(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct")
    monkeypatch.setenv("SNOWFLAKE_TOKEN", "t")
    post = MagicMock(return_value=_resp(200, {
        "resultSetMetaData": {"numRows": 1, "rowType": [{"name": "N"}]},
        "data": [["42"]],
    }))
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.snowflake_tool import snowflake_tool
    out = snowflake_tool().fn({"op": "query", "statement": "SELECT 42 AS N"})
    assert "42" in out and "N" in out
    assert post.call_args.args[0].endswith("/api/v2/statements")


def test_snowflake_write_needs_confirm(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct")
    monkeypatch.setenv("SNOWFLAKE_TOKEN", "t")
    post = MagicMock()
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.snowflake_tool import snowflake_tool
    out = snowflake_tool().fn({"op": "query", "statement": "INSERT INTO t VALUES (1)"})
    assert "DRY RUN" in out
    post.assert_not_called()


# --------------------------------- Databricks ------------------------------

def test_databricks_requires_config(monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, request=MagicMock())
    from maverick.tools.databricks_tool import databricks_tool
    out = databricks_tool().fn({"op": "jobs_list"})
    assert "ERROR" in out and "DATABRICKS" in out


def test_databricks_jobs_list(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://w.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "t")
    req = MagicMock(return_value=_resp(200, {"jobs": [{"job_id": 7, "settings": {"name": "etl"}}]}))
    _fake_httpx(monkeypatch, request=req)
    from maverick.tools.databricks_tool import databricks_tool
    out = databricks_tool().fn({"op": "jobs_list"})
    assert "7" in out and "etl" in out


def test_databricks_job_run_needs_confirm(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://w.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "t")
    req = MagicMock()
    _fake_httpx(monkeypatch, request=req)
    from maverick.tools.databricks_tool import databricks_tool
    out = databricks_tool().fn({"op": "job_run", "job_id": 7})
    assert "DRY RUN" in out
    req.assert_not_called()


# ---------------------------------- OneTrust -------------------------------

def test_onetrust_requires_config(monkeypatch):
    monkeypatch.delenv("ONETRUST_HOSTNAME", raising=False)
    monkeypatch.delenv("ONETRUST_TOKEN", raising=False)
    _fake_httpx(monkeypatch)
    from maverick.tools.onetrust_tool import onetrust_tool
    out = onetrust_tool().fn({"op": "get", "path": "/api/assessment/v2/assessments"})
    assert "ERROR" in out and "ONETRUST" in out


def test_onetrust_get(monkeypatch):
    monkeypatch.setenv("ONETRUST_HOSTNAME", "https://app.onetrust.com")
    monkeypatch.setenv("ONETRUST_TOKEN", "t")
    get = MagicMock(return_value=_resp(200, {"content": [{"name": "DPIA"}]}))
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.onetrust_tool import onetrust_tool
    out = onetrust_tool().fn({"op": "get", "path": "/api/assessment/v2/assessments"})
    assert "DPIA" in out
    assert get.call_args.args[0].endswith("/api/assessment/v2/assessments")


def test_onetrust_post_needs_confirm(monkeypatch):
    monkeypatch.setenv("ONETRUST_HOSTNAME", "https://app.onetrust.com")
    monkeypatch.setenv("ONETRUST_TOKEN", "t")
    post = MagicMock()
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.onetrust_tool import onetrust_tool
    out = onetrust_tool().fn({"op": "post", "path": "/api/x", "body": {"a": 1}})
    assert "DRY RUN" in out
    post.assert_not_called()


# ----------------------------------- Vertex --------------------------------

def test_vertex_requires_config(monkeypatch):
    monkeypatch.delenv("VERTEX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    _fake_httpx(monkeypatch)
    from maverick.tools.vertex_tool import vertex_tool
    out = vertex_tool().fn({"op": "generate", "prompt": "hi"})
    assert "ERROR" in out and "VERTEX" in out


def test_vertex_generate(monkeypatch):
    monkeypatch.setenv("VERTEX_ACCESS_TOKEN", "t")
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    post = MagicMock(return_value=_resp(200, {
        "candidates": [{"content": {"parts": [{"text": "hello from vertex"}]}}]
    }))
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.vertex_tool import vertex_tool
    out = vertex_tool().fn({"op": "generate", "model": "gemini-2.5-pro", "prompt": "hi"})
    assert out == "hello from vertex"
    assert ":generateContent" in post.call_args.args[0]
