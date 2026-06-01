"""Q3 2026 batch 11 — eight integration tools shipped together.

PagerDuty / Salesforce / Cloudflare / Datadog / HubSpot / Twilio /
S3 / Elasticsearch / GitHub Actions.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _fake_httpx(monkeypatch, **methods):
    """Install a dummy httpx module with the given methods (get/post/...) ."""
    mod = types.ModuleType("httpx")
    for name, value in methods.items():
        setattr(mod, name, value)
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def _resp(status: int, body: object):
    r = MagicMock()
    r.status_code = status
    if isinstance(body, (dict, list)):
        r.json = MagicMock(return_value=body)
        r.text = str(body)
    else:
        r.json = MagicMock(side_effect=ValueError("not json"))
        r.text = str(body)
    return r


# ---------- PagerDuty ----------

def test_pagerduty_requires_op():
    from maverick.tools.pagerduty_tool import pagerduty_tool
    assert "op is required" in pagerduty_tool().fn({})


def test_pagerduty_missing_token(monkeypatch):
    monkeypatch.delenv("PAGERDUTY_API_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "incidents"})
    assert "PAGERDUTY_API_TOKEN" in out


def test_pagerduty_incidents_renders(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "tok")
    body = {"incidents": [
        {"id": "PQ1", "status": "triggered", "urgency": "high",
         "title": "DB down"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "incidents"})
    assert "PQ1" in out and "DB down" in out


def test_pagerduty_acknowledge_dry_run(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "tok")
    _fake_httpx(monkeypatch, get=MagicMock(), put=MagicMock())
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "acknowledge", "id": "PQ1"})
    assert "DRY RUN" in out


def test_pagerduty_trigger_dry_run(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "tok")
    monkeypatch.setenv("PAGERDUTY_EVENTS_KEY", "rk")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "trigger", "summary": "db down"})
    assert "DRY RUN" in out


def test_pagerduty_acknowledge_sends_from_header(monkeypatch):
    # Issue #475: the status PUT needs a `From` header (requester email) or the
    # REST API 400s 'Requester User Not Found' with an account-level token.
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "tok")
    monkeypatch.setenv("PAGERDUTY_FROM", "oncall@example.com")
    put = MagicMock(return_value=_resp(200, {"incident": {"status": "acknowledged"}}))
    _fake_httpx(monkeypatch, put=put)
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "acknowledge", "id": "PQ1", "confirm": True})
    assert "acknowledged" in out
    # The From header was sent on the PUT.
    headers = put.call_args.kwargs["headers"]
    assert headers.get("From") == "oncall@example.com"


def test_pagerduty_acknowledge_errors_without_from(monkeypatch):
    monkeypatch.delenv("PAGERDUTY_FROM", raising=False)
    monkeypatch.delenv("PAGERDUTY_USER_EMAIL", raising=False)
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "tok")
    put = MagicMock()
    _fake_httpx(monkeypatch, put=put)
    from maverick.tools.pagerduty_tool import pagerduty_tool
    out = pagerduty_tool().fn({"op": "acknowledge", "id": "PQ1", "confirm": True})
    assert "requester email" in out.lower()
    put.assert_not_called()  # no doomed request fired


# ---------- Salesforce ----------

def test_salesforce_requires_op():
    from maverick.tools.salesforce_tool import salesforce_tool
    assert "op is required" in salesforce_tool().fn({})


def test_salesforce_missing_config(monkeypatch):
    monkeypatch.delenv("SALESFORCE_INSTANCE_URL", raising=False)
    monkeypatch.delenv("SALESFORCE_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.salesforce_tool import salesforce_tool
    out = salesforce_tool().fn({"op": "soql", "query": "SELECT Id FROM Account LIMIT 1"})
    assert "SALESFORCE_INSTANCE_URL" in out


def test_salesforce_soql_renders(monkeypatch):
    monkeypatch.setenv("SALESFORCE_INSTANCE_URL", "https://x.my.salesforce.com")
    monkeypatch.setenv("SALESFORCE_ACCESS_TOKEN", "tok")
    body = {"totalSize": 1, "done": True,
            "records": [{"attributes": {"type": "Account"}, "Id": "001x", "Name": "Acme"}]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.salesforce_tool import salesforce_tool
    out = salesforce_tool().fn({"op": "soql", "query": "SELECT Id FROM Account"})
    assert "totalSize=1" in out and "001x" in out and "Acme" in out


def test_salesforce_record_create_dry_run(monkeypatch):
    monkeypatch.setenv("SALESFORCE_INSTANCE_URL", "https://x")
    monkeypatch.setenv("SALESFORCE_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.salesforce_tool import salesforce_tool
    out = salesforce_tool().fn({
        "op": "record_create", "sobject": "Account",
        "fields": {"Name": "Acme"},
    })
    assert "DRY RUN" in out


# ---------- Cloudflare ----------

def test_cloudflare_requires_op():
    from maverick.tools.cloudflare_tool import cloudflare_tool
    assert "op is required" in cloudflare_tool().fn({})


def test_cloudflare_missing_token(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.cloudflare_tool import cloudflare_tool
    out = cloudflare_tool().fn({"op": "dns_list", "zone_id": "z"})
    assert "CLOUDFLARE_API_TOKEN" in out


def test_cloudflare_dns_list(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    body = {"success": True, "result": [
        {"id": "r1", "type": "A", "name": "x.example.com", "content": "1.2.3.4"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.cloudflare_tool import cloudflare_tool
    out = cloudflare_tool().fn({"op": "dns_list", "zone_id": "z"})
    assert "x.example.com" in out and "1.2.3.4" in out


def test_cloudflare_purge_dry_run(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.cloudflare_tool import cloudflare_tool
    out = cloudflare_tool().fn({"op": "purge", "zone_id": "z"})
    assert "DRY RUN" in out and "EVERYTHING" in out


# ---------- Datadog ----------

def test_datadog_requires_op():
    from maverick.tools.datadog_tool import datadog_tool
    assert "op is required" in datadog_tool().fn({})


def test_datadog_submit_event_validation(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.datadog_tool import datadog_tool
    out = datadog_tool().fn({"op": "submit_event"})
    assert "requires title" in out


def test_datadog_submit_event_dry_run(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    _fake_httpx(
        monkeypatch,
        post=MagicMock(return_value=_resp(200, {"event": {"id": 99}})),
    )
    from maverick.tools.datadog_tool import datadog_tool
    out = datadog_tool().fn({
        "op": "submit_event", "title": "deploy", "text": "v1.2 shipped",
    })
    assert "DRY RUN" in out


def test_datadog_submit_event_posts_with_confirm(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    _fake_httpx(
        monkeypatch,
        post=MagicMock(return_value=_resp(200, {"event": {"id": 99}})),
    )
    from maverick.tools.datadog_tool import datadog_tool
    out = datadog_tool().fn({
        "op": "submit_event", "title": "deploy", "text": "v1.2 shipped", "confirm": True,
    })
    assert "event id=99" in out


def test_datadog_monitors_requires_app_key(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    monkeypatch.delenv("DATADOG_APP_KEY", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.datadog_tool import datadog_tool
    out = datadog_tool().fn({"op": "monitors"})
    assert "DATADOG_APP_KEY" in out


# ---------- HubSpot ----------

def test_hubspot_requires_op():
    from maverick.tools.hubspot_tool import hubspot_tool
    assert "op is required" in hubspot_tool().fn({})


def test_hubspot_missing_token(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock(), post=MagicMock())
    from maverick.tools.hubspot_tool import hubspot_tool
    out = hubspot_tool().fn({"op": "contacts"})
    assert "HUBSPOT_TOKEN" in out


def test_hubspot_contacts_list(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "tok")
    body = {"results": [
        {"id": "1", "properties": {"email": "a@x.com",
                                    "firstname": "A", "lastname": "B"}},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.hubspot_tool import hubspot_tool
    out = hubspot_tool().fn({"op": "contacts"})
    assert "a@x.com" in out


def test_hubspot_contacts_follows_paging_after(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "tok")
    page1 = {"results": [{"id": "1", "properties": {"email": "one@x"}}],
             "paging": {"next": {"after": "cur-2"}}}
    page2 = {"results": [{"id": "2", "properties": {"email": "two@x"}}]}
    get = MagicMock(side_effect=[_resp(200, page1), _resp(200, page2)])
    _fake_httpx(monkeypatch, get=get)
    from maverick.tools.hubspot_tool import hubspot_tool
    out = hubspot_tool().fn({"op": "contacts", "limit": 50})
    assert "one@x" in out and "two@x" in out
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"]["after"] == "cur-2"


def test_hubspot_contact_create_dry_run(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.hubspot_tool import hubspot_tool
    out = hubspot_tool().fn({"op": "contact_create", "email": "x@y"})
    assert "DRY RUN" in out


# ---------- Twilio ----------

def test_twilio_requires_op():
    from maverick.tools.twilio_tool import twilio_tool
    assert "op is required" in twilio_tool().fn({})


def test_twilio_missing_credentials(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    # Provide from_ explicitly so the auth check (not the from-required
    # check) fires when sending the request.
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.twilio_tool import twilio_tool
    out = twilio_tool().fn({
        "op": "sms_send", "to": "+1", "body": "x", "from_": "+15550000", "confirm": True,
    })
    assert "TWILIO_ACCOUNT_SID" in out


def test_twilio_sms_send_dry_run(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15551234567")
    body = {"sid": "SM999", "status": "queued"}
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.twilio_tool import twilio_tool
    out = twilio_tool().fn({
        "op": "sms_send", "to": "+15555550000", "body": "hello",
    })
    assert "DRY RUN" in out


def test_twilio_sms_send_posts_with_confirm(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15551234567")
    body = {"sid": "SM999", "status": "queued"}
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.twilio_tool import twilio_tool
    out = twilio_tool().fn({
        "op": "sms_send", "to": "+15555550000", "body": "hello", "confirm": True,
    })
    assert "SM999" in out and "queued" in out


def test_twilio_sms_send_requires_from(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.twilio_tool import twilio_tool
    out = twilio_tool().fn({"op": "sms_send", "to": "+1", "body": "x"})
    assert "from_" in out


# ---------- S3 ----------

def test_s3_requires_op():
    from maverick.tools.s3_tool import s3_tool
    assert "op is required" in s3_tool().fn({})


def test_s3_missing_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    from maverick.tools.s3_tool import s3_tool
    out = s3_tool().fn({"op": "list_buckets"})
    assert "boto3 not installed" in out


def _install_fake_boto3(monkeypatch, *, buckets=None, list_objects=None,
                        get_body=None, get_size=None, presigned_url="https://x"):
    boto3 = types.ModuleType("boto3")

    class _Body:
        def __init__(self, data):
            self._data = data

        def read(self, n):
            return self._data[:n]

    class _Client:
        def list_buckets(self):
            return {"Buckets": buckets or []}

        def list_objects_v2(self, **kwargs):
            return {"Contents": list_objects or []}

        def get_object(self, Bucket, Key):
            return {
                "Body": _Body((get_body or "hello").encode("utf-8")),
                "ContentLength": get_size if get_size is not None else 5,
                "ContentType": "text/plain",
            }

        def put_object(self, **kwargs):
            return {}

        def delete_object(self, **kwargs):
            return {}

        def generate_presigned_url(self, *a, **k):
            return presigned_url

    boto3.client = lambda *a, **k: _Client()
    monkeypatch.setitem(sys.modules, "boto3", boto3)


def test_s3_list_buckets(monkeypatch):
    import datetime as _dt
    _install_fake_boto3(monkeypatch, buckets=[
        {"Name": "b1", "CreationDate": _dt.datetime(2026, 1, 1)},
    ])
    from maverick.tools.s3_tool import s3_tool
    out = s3_tool().fn({"op": "list_buckets"})
    assert "b1" in out


def test_s3_put_dry_run(monkeypatch):
    _install_fake_boto3(monkeypatch)
    from maverick.tools.s3_tool import s3_tool
    out = s3_tool().fn({
        "op": "put", "bucket": "b", "key": "k", "body": "hi",
    })
    assert "DRY RUN" in out


def test_s3_put_confirmed(monkeypatch):
    _install_fake_boto3(monkeypatch)
    from maverick.tools.s3_tool import s3_tool
    out = s3_tool().fn({
        "op": "put", "bucket": "b", "key": "k", "body": "hi",
        "confirm": True,
    })
    assert "put s3://b/k" in out


def test_s3_presign_returns_url(monkeypatch):
    _install_fake_boto3(monkeypatch, presigned_url="https://x.example/k?sig=abc")
    from maverick.tools.s3_tool import s3_tool
    out = s3_tool().fn({"op": "presign", "bucket": "b", "key": "k"})
    assert "https://x.example/k?sig=abc" in out


# ---------- Elasticsearch ----------

def test_elasticsearch_requires_op():
    from maverick.tools.elasticsearch_tool import elasticsearch_tool
    assert "op is required" in elasticsearch_tool().fn({})


def test_elasticsearch_missing_url(monkeypatch):
    monkeypatch.delenv("ES_URL", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.elasticsearch_tool import elasticsearch_tool
    out = elasticsearch_tool().fn({"op": "search", "index": "x"})
    assert "ES_URL" in out


def test_elasticsearch_search_renders(monkeypatch):
    monkeypatch.setenv("ES_URL", "http://es.local:9200")
    body = {
        "took": 5,
        "hits": {"total": {"value": 1}, "hits": [
            {"_id": "1", "_score": 1.5, "_source": {"name": "alice"}},
        ]},
    }
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.elasticsearch_tool import elasticsearch_tool
    out = elasticsearch_tool().fn({"op": "search", "index": "users"})
    assert "total=1" in out and "alice" in out


def test_elasticsearch_index_dry_run(monkeypatch):
    monkeypatch.setenv("ES_URL", "http://es")
    _fake_httpx(monkeypatch, put=MagicMock())
    from maverick.tools.elasticsearch_tool import elasticsearch_tool
    out = elasticsearch_tool().fn({
        "op": "index", "index": "u", "doc_id": "1", "body": {"a": 1},
    })
    assert "DRY RUN" in out


# ---------- GitHub Actions ----------

def test_gha_requires_op():
    from maverick.tools.github_actions import github_actions
    assert "op is required" in github_actions().fn({})


def test_gha_missing_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.github_actions import github_actions
    out = github_actions().fn({"op": "runs", "owner": "o", "repo": "r"})
    assert "GITHUB_TOKEN" in out


def test_gha_runs_list(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    body = {"workflow_runs": [
        {"id": 111, "name": "CI", "status": "completed",
         "conclusion": "success", "head_branch": "main", "event": "push"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.github_actions import github_actions
    out = github_actions().fn({"op": "runs", "owner": "o", "repo": "r"})
    assert "111" in out and "success" in out


def test_gha_dispatch_dry_run(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.github_actions import github_actions
    out = github_actions().fn({
        "op": "dispatch", "owner": "o", "repo": "r",
        "workflow": "ci.yml", "ref": "main",
    })
    assert "DRY RUN" in out


def test_gha_cancel_confirmed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(202, {})))
    from maverick.tools.github_actions import github_actions
    out = github_actions().fn({
        "op": "cancel", "owner": "o", "repo": "r", "run_id": 42,
        "confirm": True,
    })
    assert "cancelled run 42" in out


# ---------- registration smoke (all 8 tools land) ----------

def test_all_eight_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("pagerduty", "salesforce", "cloudflare", "datadog",
              "hubspot", "twilio", "s3", "elasticsearch", "github_actions"):
        assert n in names, f"{n} not registered"
