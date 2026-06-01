"""Q3 2026 batch 14 — Azure/Bedrock providers, 8 SaaS tools, cron scheduler.

Trello / Replicate / NewsAPI / Wolfram / Dropbox / MS Graph /
Confluence / Gmail + maverick.scheduler.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


def _fake_httpx(monkeypatch, **methods):
    mod = types.ModuleType("httpx")
    for n, v in methods.items():
        setattr(mod, n, v)
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def _resp(status, body, *, text=None):
    r = MagicMock()
    r.status_code = status
    if isinstance(body, (dict, list)):
        r.json = MagicMock(return_value=body)
        r.text = text if text is not None else str(body)
    else:
        r.json = MagicMock(side_effect=ValueError("not json"))
        r.text = text if text is not None else str(body)
    r.content = (body if isinstance(body, bytes) else str(body).encode())
    return r


def _openai_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


_needs_openai = pytest.mark.skipif(
    not _openai_available(), reason="openai extra not installed")


# ---------- Providers ----------

def test_providers_registered():
    from maverick.providers import KNOWN_PROVIDERS
    assert "azure" in KNOWN_PROVIDERS
    assert "bedrock" in KNOWN_PROVIDERS


@_needs_openai
def test_azure_requires_config(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    from maverick.providers.azure_openai_provider import AzureOpenAIClient
    try:
        AzureOpenAIClient()
    except RuntimeError as e:
        assert "AZURE_OPENAI_ENDPOINT" in str(e)
        return
    raise AssertionError("expected RuntimeError")


@_needs_openai
def test_azure_uses_dedicated_client(monkeypatch):
    """The provider must build the SDK's AzureOpenAI client (which sends
    the api-key header + api-version query), NOT a plain OpenAI client
    with the api-version baked into base_url (the SDK drops it)."""
    from openai import AzureOpenAI
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt5")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    from maverick.providers.azure_openai_provider import AzureOpenAIClient
    c = AzureOpenAIClient()
    assert isinstance(c._sync, AzureOpenAI)
    assert c.deployment == "gpt5"
    assert c.api_version == "2024-10-21"
    assert c.endpoint == "https://res.openai.azure.com"
    assert c.DEFAULT_MODEL == "gpt5"


@_needs_openai
def test_bedrock_requires_region(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    from maverick.providers.bedrock_provider import BedrockClient
    try:
        BedrockClient()
    except RuntimeError as e:
        assert "AWS_REGION" in str(e)
        return
    raise AssertionError("expected RuntimeError")


@_needs_openai
def test_bedrock_builds_url(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_API_KEY", "k")
    from maverick.providers.bedrock_provider import BedrockClient
    c = BedrockClient()
    assert "bedrock-runtime.us-east-1.amazonaws.com" in c.base_url


# ---------- Trello ----------

def test_trello_requires_op():
    from maverick.tools.trello_tool import trello_tool
    assert "op is required" in trello_tool().fn({})


def test_trello_missing_auth(monkeypatch):
    monkeypatch.delenv("TRELLO_KEY", raising=False)
    monkeypatch.delenv("TRELLO_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.trello_tool import trello_tool
    out = trello_tool().fn({"op": "boards"})
    assert "TRELLO_KEY" in out


def test_trello_boards_renders(monkeypatch):
    monkeypatch.setenv("TRELLO_KEY", "k")
    monkeypatch.setenv("TRELLO_TOKEN", "t")
    body = [{"id": "b1", "name": "Roadmap", "closed": False}]
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.trello_tool import trello_tool
    out = trello_tool().fn({"op": "boards"})
    assert "Roadmap" in out


def test_trello_card_create_dry_run(monkeypatch):
    monkeypatch.setenv("TRELLO_KEY", "k")
    monkeypatch.setenv("TRELLO_TOKEN", "t")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.trello_tool import trello_tool
    out = trello_tool().fn({"op": "card_create", "list_id": "L", "name": "Do it"})
    assert "DRY RUN" in out


# ---------- Replicate ----------

def test_replicate_requires_op():
    from maverick.tools.replicate_tool import replicate_tool
    assert "op is required" in replicate_tool().fn({})


def test_replicate_missing_token(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock(), post=MagicMock())
    from maverick.tools.replicate_tool import replicate_tool
    out = replicate_tool().fn({"op": "predict_get", "prediction_id": "p1"})
    assert "REPLICATE_API_TOKEN" in out


def test_replicate_run_creates_prediction(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_xx")
    # version resolve (GET) then create (POST)
    get_resp = _resp(200, {"latest_version": {"id": "ver123"}})
    post_resp = _resp(201, {"id": "pred1", "status": "starting"})
    _fake_httpx(monkeypatch,
                get=MagicMock(return_value=get_resp),
                post=MagicMock(return_value=post_resp))
    from maverick.tools.replicate_tool import replicate_tool
    out = replicate_tool().fn({
        "op": "run", "model": "stability-ai/sdxl", "input": {"prompt": "cat"},
    })
    assert "pred1" in out and "starting" in out


def test_replicate_cancel_dry_run(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_xx")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.replicate_tool import replicate_tool
    out = replicate_tool().fn({"op": "cancel", "prediction_id": "p1"})
    assert "DRY RUN" in out


# ---------- NewsAPI ----------

def test_newsapi_requires_op():
    from maverick.tools.newsapi_tool import newsapi_tool
    assert "op is required" in newsapi_tool().fn({})


def test_newsapi_missing_key(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.newsapi_tool import newsapi_tool
    out = newsapi_tool().fn({"op": "top_headlines"})
    assert "NEWSAPI_KEY" in out


def test_newsapi_search_renders(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "k")
    body = {"status": "ok", "totalResults": 1, "articles": [
        {"source": {"name": "TechCrunch"}, "title": "AI breakthrough",
         "url": "https://tc/1"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.newsapi_tool import newsapi_tool
    out = newsapi_tool().fn({"op": "search", "query": "ai"})
    assert "AI breakthrough" in out and "TechCrunch" in out


# ---------- Wolfram ----------

def test_wolfram_requires_query():
    from maverick.tools.wolfram_tool import wolfram_tool
    out = wolfram_tool().fn({"op": "short"})
    assert "query is required" in out


def test_wolfram_missing_appid(monkeypatch):
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.wolfram_tool import wolfram_tool
    out = wolfram_tool().fn({"op": "short", "query": "2+2"})
    assert "WOLFRAM_APP_ID" in out


def test_wolfram_short_renders(monkeypatch):
    monkeypatch.setenv("WOLFRAM_APP_ID", "app")
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, "4", text="4")))
    from maverick.tools.wolfram_tool import wolfram_tool
    out = wolfram_tool().fn({"op": "short", "query": "2+2"})
    assert out == "4"


# ---------- Dropbox ----------

def test_dropbox_requires_op():
    from maverick.tools.dropbox_tool import dropbox_tool
    assert "op is required" in dropbox_tool().fn({})


def test_dropbox_missing_token(monkeypatch):
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.dropbox_tool import dropbox_tool
    out = dropbox_tool().fn({"op": "list", "path": "/"})
    assert "DROPBOX_ACCESS_TOKEN" in out


def test_dropbox_upload_dry_run(monkeypatch):
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.dropbox_tool import dropbox_tool
    out = dropbox_tool().fn({"op": "upload", "path": "/x.txt", "content": "hi"})
    assert "DRY RUN" in out




def test_dropbox_share_dry_run(monkeypatch):
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "tok")
    post = MagicMock()
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.dropbox_tool import dropbox_tool
    out = dropbox_tool().fn({"op": "share", "path": "/x.txt"})
    assert "DRY RUN" in out
    post.assert_not_called()
def test_dropbox_list_renders(monkeypatch):
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "tok")
    body = {"entries": [
        {".tag": "file", "name": "a.txt", "size": 10, "path_display": "/a.txt"},
    ]}
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.dropbox_tool import dropbox_tool
    out = dropbox_tool().fn({"op": "list", "path": ""})
    assert "/a.txt" in out


# ---------- MS Graph ----------

def test_msgraph_requires_op():
    from maverick.tools.msgraph_tool import msgraph_tool
    assert "op is required" in msgraph_tool().fn({})


def test_msgraph_missing_token(monkeypatch):
    monkeypatch.delenv("MSGRAPH_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.msgraph_tool import msgraph_tool
    out = msgraph_tool().fn({"op": "me"})
    assert "MSGRAPH_ACCESS_TOKEN" in out


def test_msgraph_send_mail_dry_run(monkeypatch):
    monkeypatch.setenv("MSGRAPH_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.msgraph_tool import msgraph_tool
    out = msgraph_tool().fn({
        "op": "send_mail", "to": ["a@x"], "subject": "hi", "body": "yo",
    })
    assert "DRY RUN" in out


def test_msgraph_messages_renders(monkeypatch):
    monkeypatch.setenv("MSGRAPH_ACCESS_TOKEN", "tok")
    body = {"value": [{
        "subject": "Standup", "isRead": False,
        "from": {"emailAddress": {"address": "boss@x"}},
    }]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.msgraph_tool import msgraph_tool
    out = msgraph_tool().fn({"op": "messages"})
    assert "Standup" in out and "boss@x" in out


# ---------- Confluence ----------

def test_confluence_requires_op():
    from maverick.tools.confluence_tool import confluence_tool
    assert "op is required" in confluence_tool().fn({})


def test_confluence_missing_config(monkeypatch):
    for k in ("CONFLUENCE_URL", "CONFLUENCE_USER", "CONFLUENCE_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.confluence_tool import confluence_tool
    out = confluence_tool().fn({"op": "search", "cql": "text ~ 'x'"})
    assert "CONFLUENCE_URL" in out


def test_confluence_page_get_strips_html(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://x.atlassian.net/wiki")
    monkeypatch.setenv("CONFLUENCE_USER", "u@x")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok")
    body = {
        "id": "123", "title": "Roadmap",
        "space": {"key": "ENG"}, "version": {"number": 3},
        "body": {"storage": {"value": "<p>Hello <b>world</b></p>"}},
    }
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.confluence_tool import confluence_tool
    out = confluence_tool().fn({"op": "page_get", "page_id": "123"})
    assert "Hello world" in out and "<p>" not in out


def test_confluence_page_create_dry_run(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://x.atlassian.net/wiki")
    monkeypatch.setenv("CONFLUENCE_USER", "u@x")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.confluence_tool import confluence_tool
    out = confluence_tool().fn({
        "op": "page_create", "space_key": "ENG", "title": "New",
    })
    assert "DRY RUN" in out


def _confluence_env(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://x.atlassian.net/wiki")
    monkeypatch.setenv("CONFLUENCE_USER", "u@x")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok")


def test_confluence_page_create_sends_space_key(monkeypatch):
    # Issue #475: the v1 content API keys space by KEY (space.key). Confirm the
    # space_key arg lands in payload["space"]["key"].
    _confluence_env(monkeypatch)
    post = MagicMock(return_value=_resp(200, {"id": "999", "title": "New"}))
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.confluence_tool import confluence_tool
    confluence_tool().fn({
        "op": "page_create", "space_key": "ENG", "title": "New",
        "body": "<p>hi</p>", "confirm": True,
    })
    payload = post.call_args.kwargs["json"]
    assert payload["space"]["key"] == "ENG"


def test_confluence_page_create_accepts_legacy_space_id(monkeypatch):
    # Back-compat: the old `space_id` arg still works (treated as the key).
    _confluence_env(monkeypatch)
    post = MagicMock(return_value=_resp(200, {"id": "999", "title": "New"}))
    _fake_httpx(monkeypatch, post=post)
    from maverick.tools.confluence_tool import confluence_tool
    confluence_tool().fn({
        "op": "page_create", "space_id": "ENG", "title": "New", "confirm": True,
    })
    assert post.call_args.kwargs["json"]["space"]["key"] == "ENG"


# ---------- Gmail ----------

def test_gmail_requires_op():
    from maverick.tools.gmail_tool import gmail_tool
    assert "op is required" in gmail_tool().fn({})


def test_gmail_missing_token(monkeypatch):
    monkeypatch.delenv("GMAIL_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.gmail_tool import gmail_tool
    out = gmail_tool().fn({"op": "labels"})
    assert "GMAIL_ACCESS_TOKEN" in out


def test_gmail_send_dry_run(monkeypatch):
    monkeypatch.setenv("GMAIL_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.gmail_tool import gmail_tool
    out = gmail_tool().fn({
        "op": "send", "to": "a@x", "subject": "hi", "body": "yo",
    })
    assert "DRY RUN" in out


def test_gmail_send_confirmed(monkeypatch):
    monkeypatch.setenv("GMAIL_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch,
                post=MagicMock(return_value=_resp(200, {"id": "m1"})))
    from maverick.tools.gmail_tool import gmail_tool
    out = gmail_tool().fn({
        "op": "send", "to": "a@x", "subject": "hi", "body": "yo",
        "confirm": True,
    })
    assert "sent" in out and "m1" in out


# ---------- Scheduler ----------

def test_scheduler_parse_basic():
    from maverick.scheduler import parse_cron
    minute, hour, dom, mon, dow = parse_cron("0 9 * * 1-5")
    assert minute == {0}
    assert hour == {9}
    assert dow == {1, 2, 3, 4, 5}


def test_scheduler_rejects_bad_field_count():
    from maverick.scheduler import CronError, parse_cron
    try:
        parse_cron("0 9 * *")
    except CronError as e:
        assert "5 fields" in str(e)
        return
    raise AssertionError("expected CronError")


def test_scheduler_step_syntax():
    from maverick.scheduler import parse_cron
    minute, *_ = parse_cron("*/15 * * * *")
    assert minute == {0, 15, 30, 45}


def test_scheduler_single_value_step_expands():
    """'5/15' means 5,20,35,50 — not just {5}."""
    from maverick.scheduler import parse_cron
    minute, *_ = parse_cron("5/15 * * * *")
    assert minute == {5, 20, 35, 50}


def test_scheduler_sunday_as_7_accepted():
    """'7' and ranges containing 7 are Sunday, folded to 0 — not rejected."""
    from maverick.scheduler import parse_cron
    *_, dow = parse_cron("0 9 * * 7")
    assert dow == {0}
    *_, dow2 = parse_cron("0 9 * * 5-7")
    assert dow2 == {5, 6, 0}


def test_scheduler_next_run_daily_9am_utc():
    import datetime as _dt

    from maverick.scheduler import next_run
    # Monday 2026-06-01 08:00 UTC -> next "0 9 * * *" is same day 09:00 UTC.
    base = _dt.datetime(2026, 6, 1, 8, 0, tzinfo=_dt.timezone.utc).timestamp()
    ts = next_run("0 9 * * *", after=base)
    got = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    assert got.hour == 9 and got.minute == 0
    assert got.date() == _dt.date(2026, 6, 1)


def test_scheduler_next_run_weekday_only_utc():
    import datetime as _dt

    from maverick.scheduler import next_run
    # Friday 2026-06-05 10:00 UTC, "0 9 * * 1-5" -> Monday 2026-06-08 09:00.
    base = _dt.datetime(2026, 6, 5, 10, 0, tzinfo=_dt.timezone.utc).timestamp()
    ts = next_run("0 9 * * 1-5", after=base)
    got = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    assert got.weekday() == 0  # Monday
    assert got.date() == _dt.date(2026, 6, 8)


def test_scheduler_next_run_is_utc():
    """Fields match UTC regardless of host TZ — '0 0 * * *' is 00:00 UTC."""
    import datetime as _dt

    from maverick.scheduler import next_run
    base = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=_dt.timezone.utc).timestamp()
    ts = next_run("0 0 * * *", after=base)
    got = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    assert got.hour == 0 and got.minute == 0
    assert got.date() == _dt.date(2026, 6, 2)


def test_scheduler_schedule_cron_enqueues(tmp_path):
    import datetime as _dt

    from maverick.job_queue import JobQueue
    from maverick.scheduler import schedule_cron
    q = JobQueue(db_path=tmp_path / "jobs.db")
    base = _dt.datetime(2026, 6, 1, 8, 0, 0).timestamp()
    job_id, run_at = schedule_cron(q, "0 9 * * *", "run_goal",
                                    {"goal_id": 1}, after=base)
    assert job_id > 0
    job = q.get(job_id)
    assert job is not None
    assert job.kind == "run_goal"
    assert abs(job.run_at - run_at) < 1.0
    # Not claimable before run_at.
    assert q.claim(now=base) is None
    # Claimable at/after run_at.
    assert q.claim(now=run_at + 1) is not None


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("trello", "replicate", "newsapi", "wolfram", "dropbox",
              "msgraph", "confluence", "gmail"):
        assert n in names, f"{n} not registered"
