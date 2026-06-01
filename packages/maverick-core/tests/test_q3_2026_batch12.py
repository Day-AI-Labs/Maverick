"""Q3 2026 batch 12 — 7 more SaaS tools + circuit breaker.

Airtable / Asana / ClickUp / AWS Lambda / DynamoDB / Vercel /
Google Drive + a per-key circuit-breaker primitive.
"""
from __future__ import annotations

import sys
import time
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
    if isinstance(body, (dict, list)):
        r.json = MagicMock(return_value=body)
        r.text = str(body)
    elif isinstance(body, str):
        r.json = MagicMock(side_effect=ValueError("not json"))
        r.text = body
    else:
        r.json = MagicMock(return_value=body)
        r.text = str(body)
    r.content = (body if isinstance(body, bytes) else str(body).encode("utf-8"))
    return r


# ---------- Airtable ----------

def test_airtable_requires_op():
    from maverick.tools.airtable_tool import airtable_tool
    assert "op is required" in airtable_tool().fn({})


def test_airtable_missing_key(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.airtable_tool import airtable_tool
    out = airtable_tool().fn({"op": "list", "table": "Tasks"})
    assert "AIRTABLE_API_KEY" in out


def test_airtable_list_renders(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appB")
    body = {"records": [
        {"id": "rec1", "fields": {"Name": "Alice", "Score": 99}},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.airtable_tool import airtable_tool
    out = airtable_tool().fn({"op": "list", "table": "People"})
    assert "rec1" in out and "Alice" in out


def test_airtable_create_dry_run(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appB")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.airtable_tool import airtable_tool
    out = airtable_tool().fn({
        "op": "create", "table": "T", "fields": {"Name": "X"},
    })
    assert "DRY RUN" in out


# ---------- Asana ----------

def test_asana_requires_op():
    from maverick.tools.asana_tool import asana_tool
    assert "op is required" in asana_tool().fn({})


def test_asana_missing_token(monkeypatch):
    monkeypatch.delenv("ASANA_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.asana_tool import asana_tool
    out = asana_tool().fn({"op": "workspaces"})
    assert "ASANA_TOKEN" in out


def test_asana_workspaces(monkeypatch):
    monkeypatch.setenv("ASANA_TOKEN", "tok")
    body = {"data": [{"gid": "1", "name": "Acme"}]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.asana_tool import asana_tool
    out = asana_tool().fn({"op": "workspaces"})
    assert "Acme" in out


def test_asana_task_complete_dry_run(monkeypatch):
    monkeypatch.setenv("ASANA_TOKEN", "tok")
    _fake_httpx(monkeypatch, put=MagicMock())
    from maverick.tools.asana_tool import asana_tool
    out = asana_tool().fn({"op": "task_complete", "task_gid": "1"})
    assert "DRY RUN" in out


# ---------- ClickUp ----------

def test_clickup_requires_op():
    from maverick.tools.clickup_tool import clickup_tool
    assert "op is required" in clickup_tool().fn({})


def test_clickup_missing_token(monkeypatch):
    monkeypatch.delenv("CLICKUP_API_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.clickup_tool import clickup_tool
    out = clickup_tool().fn({"op": "teams"})
    assert "CLICKUP_API_TOKEN" in out


def test_clickup_teams(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "tok")
    body = {"teams": [{"id": "1", "name": "Team Alpha"}]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.clickup_tool import clickup_tool
    out = clickup_tool().fn({"op": "teams"})
    assert "Team Alpha" in out


def test_clickup_task_create_dry_run(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.clickup_tool import clickup_tool
    out = clickup_tool().fn({
        "op": "task_create", "list_id": "L1", "name": "Do it",
    })
    assert "DRY RUN" in out


def test_clickup_tasks_follows_pagination(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "tok")
    page0 = {"tasks": [{"id": "t1", "name": "first"}], "last_page": False}
    page1 = {"tasks": [{"id": "t2", "name": "second"}], "last_page": True}
    get = MagicMock(side_effect=[_resp(200, page0), _resp(200, page1)])
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.clickup_tool import clickup_tool
    out = clickup_tool().fn({"op": "tasks", "list_id": "L1", "limit": 50})
    # Both pages' tasks appear; the loop stopped at last_page.
    assert "first" in out and "second" in out
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["params"]["page"] == 0
    assert get.call_args_list[1].kwargs["params"]["page"] == 1


def test_clickup_tasks_stops_at_limit(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "tok")
    # last_page never True, but limit=1 must stop after the first page.
    page = {"tasks": [{"id": "t1", "name": "only"}], "last_page": False}
    get = MagicMock(return_value=_resp(200, page))
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.clickup_tool import clickup_tool
    out = clickup_tool().fn({"op": "tasks", "list_id": "L1", "limit": 1})
    assert "only" in out
    assert get.call_count == 1


# ---------- Lambda ----------

def _install_fake_boto3_lambda(monkeypatch, *, functions=None,
                               invoke_payload=b"{}", invoke_status=200,
                               function_cfg=None, log_events=None):
    boto3 = types.ModuleType("boto3")

    class _LambdaClient:
        def list_functions(self, **k):
            return {"Functions": functions or []}

        def invoke(self, **k):
            body = MagicMock()
            body.read = lambda: invoke_payload
            return {"StatusCode": invoke_status, "Payload": body}

        def get_function(self, **k):
            return {"Configuration": function_cfg or
                    {"FunctionName": k.get("FunctionName"), "Runtime": "python3.12"}}

    class _LogsClient:
        def filter_log_events(self, **k):
            return {"events": log_events or []}

    def _client(service, *a, **kw):
        if service == "lambda":
            return _LambdaClient()
        if service == "logs":
            return _LogsClient()
        raise AssertionError(service)

    boto3.client = _client
    monkeypatch.setitem(sys.modules, "boto3", boto3)


def test_lambda_requires_op():
    from maverick.tools.lambda_tool import lambda_tool
    assert "op is required" in lambda_tool().fn({})


def test_lambda_missing_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    from maverick.tools.lambda_tool import lambda_tool
    out = lambda_tool().fn({"op": "list_functions"})
    assert "boto3 not installed" in out


def test_lambda_list_functions(monkeypatch):
    _install_fake_boto3_lambda(monkeypatch, functions=[
        {"FunctionName": "my-fn", "Runtime": "python3.12",
         "MemorySize": 512, "Timeout": 30},
    ])
    from maverick.tools.lambda_tool import lambda_tool
    out = lambda_tool().fn({"op": "list_functions"})
    assert "my-fn" in out and "python3.12" in out


def test_lambda_invoke_dry_run(monkeypatch):
    _install_fake_boto3_lambda(monkeypatch)
    from maverick.tools.lambda_tool import lambda_tool
    out = lambda_tool().fn({
        "op": "invoke", "function_name": "my-fn",
        "payload": {"x": 1}, "invocation_type": "RequestResponse",
    })
    assert "DRY RUN" in out


def test_lambda_invoke_confirmed(monkeypatch):
    _install_fake_boto3_lambda(monkeypatch, invoke_payload=b'{"ok": true}')
    from maverick.tools.lambda_tool import lambda_tool
    out = lambda_tool().fn({
        "op": "invoke", "function_name": "my-fn",
        "payload": {}, "confirm": True,
    })
    assert "status=200" in out and "ok" in out


# ---------- DynamoDB ----------

def _install_fake_boto3_ddb(monkeypatch, *, tables=None, item=None,
                            query_items=None, scan_items=None):
    boto3 = types.ModuleType("boto3")

    class _Meta:
        def __init__(self, c):
            self.client = c

    class _LL:
        def list_tables(self):
            return {"TableNames": tables or []}

    class _Table:
        def __init__(self, name):
            self.name = name

        def get_item(self, **k):
            return {"Item": item} if item is not None else {}

        def put_item(self, **k):
            return {}

        def delete_item(self, **k):
            return {}

        def query(self, **k):
            return {"Items": query_items or [], "Count": len(query_items or [])}

        def scan(self, **k):
            return {"Items": scan_items or [], "Count": len(scan_items or [])}

    class _Resource:
        @property
        def meta(self):
            return _Meta(_LL())

        def Table(self, name):
            return _Table(name)

    boto3.resource = lambda service, *a, **k: _Resource()
    boto3.client = lambda *a, **k: _LL()
    monkeypatch.setitem(sys.modules, "boto3", boto3)


def test_dynamodb_requires_op():
    from maverick.tools.dynamodb_tool import dynamodb_tool
    assert "op is required" in dynamodb_tool().fn({})


def test_dynamodb_tables(monkeypatch):
    _install_fake_boto3_ddb(monkeypatch, tables=["Users", "Orders"])
    from maverick.tools.dynamodb_tool import dynamodb_tool
    out = dynamodb_tool().fn({"op": "tables"})
    assert "Users" in out and "Orders" in out


def test_dynamodb_get(monkeypatch):
    _install_fake_boto3_ddb(monkeypatch, item={"id": "1", "name": "alice"})
    from maverick.tools.dynamodb_tool import dynamodb_tool
    out = dynamodb_tool().fn({
        "op": "get", "table": "Users", "key": {"id": "1"},
    })
    assert "alice" in out


def test_dynamodb_put_dry_run(monkeypatch):
    _install_fake_boto3_ddb(monkeypatch)
    from maverick.tools.dynamodb_tool import dynamodb_tool
    out = dynamodb_tool().fn({
        "op": "put", "table": "Users", "item": {"id": "1"},
    })
    assert "DRY RUN" in out


def test_dynamodb_query(monkeypatch):
    _install_fake_boto3_ddb(monkeypatch, query_items=[
        {"id": "1", "name": "alice"},
    ])
    from maverick.tools.dynamodb_tool import dynamodb_tool
    out = dynamodb_tool().fn({
        "op": "query", "table": "Users",
        "key_cond_expression": "id = :id",
        "expression_values": {":id": "1"},
    })
    assert "count=1" in out and "alice" in out


# ---------- Vercel ----------

def test_vercel_requires_op():
    from maverick.tools.vercel_tool import vercel_tool
    assert "op is required" in vercel_tool().fn({})


def test_vercel_missing_token(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.vercel_tool import vercel_tool
    out = vercel_tool().fn({"op": "projects"})
    assert "VERCEL_TOKEN" in out


def test_vercel_projects(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "tok")
    body = {"projects": [
        {"id": "p1", "name": "my-app", "framework": "nextjs",
         "latestDeployments": [{"readyState": "READY"}]},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.vercel_tool import vercel_tool
    out = vercel_tool().fn({"op": "projects"})
    assert "my-app" in out and "READY" in out


def test_vercel_cancel_dry_run(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "tok")
    _fake_httpx(monkeypatch, patch=MagicMock())
    from maverick.tools.vercel_tool import vercel_tool
    out = vercel_tool().fn({"op": "cancel", "deployment_id": "d1"})
    assert "DRY RUN" in out


# ---------- Google Drive ----------

def test_gdrive_requires_op():
    from maverick.tools.gdrive_tool import gdrive_tool
    assert "op is required" in gdrive_tool().fn({})


def test_gdrive_missing_token(monkeypatch):
    monkeypatch.delenv("GDRIVE_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.gdrive_tool import gdrive_tool
    out = gdrive_tool().fn({"op": "list"})
    assert "GDRIVE_ACCESS_TOKEN" in out


def test_gdrive_list_renders(monkeypatch):
    monkeypatch.setenv("GDRIVE_ACCESS_TOKEN", "tok")
    body = {"files": [
        {"id": "f1", "name": "Notes", "mimeType": "text/plain"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.gdrive_tool import gdrive_tool
    out = gdrive_tool().fn({"op": "list"})
    assert "f1" in out and "Notes" in out


def test_gdrive_create_dry_run(monkeypatch):
    monkeypatch.setenv("GDRIVE_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.gdrive_tool import gdrive_tool
    out = gdrive_tool().fn({
        "op": "create", "name": "test.txt", "content": "hi",
    })
    assert "DRY RUN" in out


# ---------- Circuit breaker ----------

def test_circuit_breaker_starts_closed():
    from maverick.circuit_breaker import CircuitBreaker, CircuitState
    br = CircuitBreaker("test1", failure_threshold=3, cooldown_seconds=1)
    assert br.state is CircuitState.CLOSED
    br.call(lambda: 42)
    assert br.state is CircuitState.CLOSED


def test_circuit_breaker_opens_after_failures():
    from maverick.circuit_breaker import (
        CircuitBreaker,
        CircuitOpen,
        CircuitState,
    )

    def _boom():
        raise RuntimeError("nope")

    br = CircuitBreaker("test2", failure_threshold=2, cooldown_seconds=10)
    for _ in range(2):
        try:
            br.call(_boom)
        except RuntimeError:
            pass
    assert br.state is CircuitState.OPEN
    try:
        br.call(lambda: 1)
    except CircuitOpen:
        return
    raise AssertionError("expected CircuitOpen")


def test_circuit_breaker_half_open_after_cooldown():
    from maverick.circuit_breaker import CircuitBreaker, CircuitState
    br = CircuitBreaker("test3", failure_threshold=1, cooldown_seconds=0.01)
    try:
        br.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    except RuntimeError:
        pass
    assert br.state is CircuitState.OPEN
    time.sleep(0.02)
    assert br.state is CircuitState.HALF_OPEN
    # A successful probe closes the breaker.
    br.call(lambda: 1)
    assert br.state is CircuitState.CLOSED


def test_circuit_breaker_half_open_failure_reopens():
    from maverick.circuit_breaker import CircuitBreaker, CircuitState
    br = CircuitBreaker("test4", failure_threshold=1, cooldown_seconds=0.01)
    try:
        br.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    except RuntimeError:
        pass
    time.sleep(0.02)
    assert br.state is CircuitState.HALF_OPEN
    try:
        br.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    except RuntimeError:
        pass
    assert br.state is CircuitState.OPEN


def test_circuit_breaker_registry_singleton():
    from maverick.circuit_breaker import get, reset_all
    reset_all()
    a = get("shared-key")
    b = get("shared-key")
    assert a is b


def test_circuit_breaker_snapshot():
    from maverick.circuit_breaker import get, reset_all, snapshot
    reset_all()
    br = get("snap-key", failure_threshold=2)
    br.record_success()
    rows = snapshot()
    assert any(r["key"] == "snap-key" for r in rows)


# ---------- registration smoke ----------

def test_new_tools_not_registered_by_default(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("airtable", "asana", "clickup", "lambda",
              "dynamodb", "vercel", "gdrive"):
        assert n not in names, f"{n} should be opt-in"


def test_new_tools_register_when_enabled(tmp_path, monkeypatch):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    monkeypatch.setenv("MAVERICK_ENABLE_CRED_TOOLS", "true")
    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("airtable", "asana", "clickup", "lambda",
              "dynamodb", "vercel", "gdrive"):
        assert n in names, f"{n} not registered"
