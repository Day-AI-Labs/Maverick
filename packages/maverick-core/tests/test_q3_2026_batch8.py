"""Q3 2026 batch 8: worker daemon, discord-bot / hackernews / dns / geocode tools."""
from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock

# ---------- Worker daemon ----------

def test_worker_runs_one_job(tmp_path):
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker

    q = JobQueue(db_path=tmp_path / "jobs.db")
    seen: list[int] = []

    def _handler(job):
        seen.append(int(job.payload.get("n", 0)))

    w = Worker(queue=q, idle_sleep=0.0)
    w.register("noop", _handler)

    jid = q.enqueue("noop", {"n": 7})
    assert w.run_once() is True
    assert seen == [7]
    job = q.get(jid)
    assert job.status == "done"


def test_worker_empty_queue_returns_false(tmp_path):
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker
    q = JobQueue(db_path=tmp_path / "jobs.db")
    w = Worker(queue=q)
    assert w.run_once() is False


def test_worker_no_handler_terminal(tmp_path):
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker
    q = JobQueue(db_path=tmp_path / "jobs.db")
    w = Worker(queue=q)
    jid = q.enqueue("nonexistent", {})
    assert w.run_once() is True
    job = q.get(jid)
    assert job.status == "failed"
    assert "no handler" in job.last_error


def test_worker_handler_exception_reschedules(tmp_path):
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker
    q = JobQueue(db_path=tmp_path / "jobs.db")
    w = Worker(queue=q, retry_after=0.0, max_attempts=3)

    def _boom(job):
        raise RuntimeError("kaboom")

    w.register("flaky", _boom)
    jid = q.enqueue("flaky", {})
    w.run_once()  # first attempt fails, reschedules
    job = q.get(jid)
    assert job.status == "pending"
    assert job.attempts == 1
    assert "kaboom" in job.last_error


def test_worker_handler_exception_terminal_after_max(tmp_path):
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker
    q = JobQueue(db_path=tmp_path / "jobs.db")
    w = Worker(queue=q, retry_after=0.0, max_attempts=2)

    def _boom(job):
        raise RuntimeError("perma-fail")

    w.register("doomed", _boom)
    jid = q.enqueue("doomed", {})
    for _ in range(5):
        if not w.run_once():
            break
    job = q.get(jid)
    assert job.status == "failed"
    assert "perma-fail" in job.last_error


def test_worker_run_forever_stop_is_clean(tmp_path):
    """run_forever must exit promptly when stop() is called."""
    import threading

    from maverick.job_queue import JobQueue
    from maverick.worker import Worker
    q = JobQueue(db_path=tmp_path / "jobs.db")
    w = Worker(queue=q, idle_sleep=0.05)

    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    w.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()


# ---------- Discord bot tool ----------

def test_discord_bot_requires_op():
    from maverick.tools.discord_bot import discord_bot
    assert "op is required" in discord_bot().fn({})


def test_discord_bot_missing_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.post = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.discord_bot import discord_bot
    out = discord_bot().fn({"op": "post", "channel_id": "123456789012345678", "content": "hi"})
    assert "DISCORD_BOT_TOKEN" in out


def test_discord_bot_post_calls_api(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot_xx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"id": "msg_42"})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.discord_bot import discord_bot
    out = discord_bot().fn({"op": "post", "channel_id": "123456789012345678", "content": "hi"})
    assert "posted to 123456789012345678" in out and "msg_42" in out


def test_discord_bot_history_renders(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot_xx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=[
        {"id": "1", "author": {"username": "alice"}, "content": "hello"},
        {"id": "2", "author": {"username": "bob"}, "content": "yo"},
    ])
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.discord_bot import discord_bot
    out = discord_bot().fn({"op": "history", "channel_id": "123456789012345678", "limit": 10})
    assert "alice: hello" in out and "bob: yo" in out


def test_discord_bot_react_validates(monkeypatch):
    fake_httpx = types.ModuleType("httpx")
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.discord_bot import discord_bot
    out = discord_bot().fn({"op": "react", "channel_id": "123456789012345678"})
    assert "channel_id, message_id, emoji" in out


def test_discord_bot_rejects_non_snowflake_ids(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot_xx")
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.discord_bot import discord_bot
    out = discord_bot().fn({"op": "lookup_channel", "channel_id": "123/../roles"})
    assert "snowflake" in out
    fake_httpx.get.assert_not_called()


# ---------- Hacker News tool ----------

def test_hn_requires_op():
    from maverick.tools.hackernews import hackernews
    assert "op is required" in hackernews().fn({})


def test_hn_top_renders(monkeypatch):
    # Two responses: the id list, then per-item fetches.
    def _make_get_side_effects():
        ids_resp = MagicMock()
        ids_resp.status_code = 200
        ids_resp.json = MagicMock(return_value=[111, 222])
        item1 = MagicMock()
        item1.status_code = 200
        item1.json = MagicMock(return_value={
            "title": "Story One", "score": 100, "descendants": 5,
            "url": "https://x/1",
        })
        item2 = MagicMock()
        item2.status_code = 200
        item2.json = MagicMock(return_value={
            "title": "Story Two", "score": 50, "descendants": 2,
            "url": "https://x/2",
        })
        return iter([ids_resp, item1, item2])

    seq = _make_get_side_effects()
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(side_effect=lambda *a, **k: next(seq))
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.hackernews import hackernews
    out = hackernews().fn({"op": "top", "limit": 2})
    assert "Story One" in out and "Story Two" in out
    assert "https://x/1" in out


def test_hn_get_story(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "id": 100, "type": "story", "title": "A story",
        "by": "alice", "score": 42, "descendants": 7,
        "url": "https://example.com", "text": "body",
    })
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.hackernews import hackernews
    out = hackernews().fn({"op": "get", "item_id": 100})
    assert "[story #100]" in out
    assert "by alice" in out


def test_hn_search_via_algolia(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"hits": [
        {"title": "DeepSeek release", "points": 200,
         "url": "https://x", "objectID": "1"},
    ]})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.hackernews import hackernews
    out = hackernews().fn({"op": "search", "query": "deepseek"})
    assert "DeepSeek release" in out


# ---------- DNS lookup tool ----------

def test_dns_requires_op():
    from maverick.tools.dns_lookup import dns_lookup
    assert "op is required" in dns_lookup().fn({})


def test_dns_socket_fallback_for_a(monkeypatch):
    """Without dnspython, A queries fall back to getaddrinfo."""
    monkeypatch.setattr(
        "maverick.tools.dns_lookup._have_dnspython", lambda: False,
    )
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, *a, **k: [
            (0, 0, 0, "", ("93.184.216.34", 0)),
        ],
    )
    from maverick.tools.dns_lookup import dns_lookup
    out = dns_lookup().fn({"op": "resolve", "host": "example.com", "type": "A"})
    assert "93.184.216.34" in out


def test_dns_socket_fallback_refuses_mx(monkeypatch):
    monkeypatch.setattr(
        "maverick.tools.dns_lookup._have_dnspython", lambda: False,
    )
    from maverick.tools.dns_lookup import dns_lookup
    out = dns_lookup().fn({"op": "resolve", "host": "example.com", "type": "MX"})
    assert "dnspython" in out


def test_dns_reverse_socket_fallback(monkeypatch):
    monkeypatch.setattr(
        "maverick.tools.dns_lookup._have_dnspython", lambda: False,
    )
    monkeypatch.setattr(
        "socket.gethostbyaddr",
        lambda ip: ("a.example.com", [], [ip]),
    )
    from maverick.tools.dns_lookup import dns_lookup
    out = dns_lookup().fn({"op": "reverse", "ip": "1.2.3.4"})
    assert "a.example.com" in out


def test_dns_reverse_requires_ip():
    from maverick.tools.dns_lookup import dns_lookup
    out = dns_lookup().fn({"op": "reverse"})
    assert "requires ip" in out


# ---------- Geocode tool ----------

def test_geocode_requires_op():
    from maverick.tools.geocode import geocode
    assert "op is required" in geocode().fn({})


def test_geocode_forward_renders(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=[{
        "lat": "37.4220", "lon": "-122.0841",
        "display_name": "1600 Amphitheatre Parkway, Mountain View, CA",
    }])
    # geocode routes through the SSRF-safe client now; mock that seam.
    import maverick.tools._ssrf as _ssrf
    monkeypatch.setattr(_ssrf, "safe_get", lambda url, **kw: resp)
    from maverick.tools.geocode import geocode
    out = geocode().fn({"op": "forward", "query": "googleplex"})
    assert "37.4220" in out
    assert "Mountain View" in out


def test_geocode_reverse_renders(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "display_name": "Liberty Island, Manhattan, NYC, NY",
        "address": {"city": "New York", "country": "USA"},
    })
    import maverick.tools._ssrf as _ssrf
    monkeypatch.setattr(_ssrf, "safe_get", lambda url, **kw: resp)
    from maverick.tools.geocode import geocode
    out = geocode().fn({"op": "reverse", "lat": 40.6892, "lon": -74.0445})
    assert "Liberty Island" in out
    assert "New York" in out


def test_geocode_reverse_requires_coords():
    from maverick.tools.geocode import geocode
    out = geocode().fn({"op": "reverse"})
    assert "lat and lon" in out


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("discord_bot", "hackernews", "dns_lookup", "geocode"):
        assert n in names, f"{n} not registered"
