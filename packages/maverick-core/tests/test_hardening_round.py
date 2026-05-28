"""Hardening regressions (review round): workflow loop-safety, circuit
breaker reconfig, scheduler impossible-schedule bound, llm_cache cap,
and crash-on-success format fixes across the SaaS tools."""
from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock


def _fake_httpx(monkeypatch, **methods):
    mod = types.ModuleType("httpx")
    for n, v in methods.items():
        setattr(mod, n, v)
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    r.text = str(body)
    return r


# ---------- crash-on-success: null fields in valid 2xx bodies ----------

def test_elasticsearch_handles_null_score(monkeypatch):
    """Sorted ES queries return hits with _score=null — must not crash."""
    monkeypatch.setenv("ES_URL", "http://es.local:9200")
    body = {"took": 3, "hits": {"total": {"value": 1}, "hits": [
        {"_id": "1", "_score": None, "_source": {"k": "v"}},
    ]}}
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.elasticsearch_tool import elasticsearch_tool
    out = elasticsearch_tool().fn({"op": "search", "index": "logs"})
    assert "ERROR" not in out
    assert "1" in out  # the doc id rendered


def test_vercel_handles_null_project_name(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "tok")
    body = {"projects": [
        {"id": "p1", "name": None, "framework": "nextjs",
         "latestDeployments": [{"readyState": "READY"}]},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.vercel_tool import vercel_tool
    out = vercel_tool().fn({"op": "projects"})
    assert "ERROR" not in out and "p1" in out


def test_datadog_handles_null_monitor_id(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "k")
    monkeypatch.setenv("DATADOG_APP_KEY", "a")
    body = [{"id": None, "overall_state": "OK", "name": "cpu"}]
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.datadog_tool import datadog_tool
    out = datadog_tool().fn({"op": "monitors"})
    assert "ERROR" not in out and "cpu" in out


def test_reddit_handles_null_score(monkeypatch):
    body = {"data": {"children": [
        {"data": {"subreddit": "x", "score": None, "num_comments": None,
                  "title": "promoted"}},
    ]}}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.reddit_tool import reddit_tool
    out = reddit_tool().fn({"op": "subreddit", "name": "x"})
    assert "ERROR" not in out and "promoted" in out


def test_ga4_guards_non_json(monkeypatch):
    monkeypatch.setenv("GA4_ACCESS_TOKEN", "t")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(side_effect=ValueError("not json"))
    resp.text = "<html>proxy error</html>"
    _fake_httpx(monkeypatch, post=MagicMock(return_value=resp))
    from maverick.tools.ga4_tool import ga4_tool
    out = ga4_tool().fn({"op": "run_report"})
    assert "non-JSON" in out  # graceful, not a raw TypeError/ValueError


def test_ses_dry_run_interpolates_subject(monkeypatch):
    # Build a fake boto3 so the tool imports cleanly; send is dry-run so
    # the client is never used.
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *a, **k: MagicMock()
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    from maverick.tools.ses_tool import ses_tool
    out = ses_tool().fn({
        "op": "send", "from_": "a@x", "to": ["b@x"],
        "subject": "Q3 report", "body": "hi",
    })
    assert "DRY RUN" in out
    assert "Q3 report" in out  # f-string actually interpolated
    assert "{subject" not in out


# ---------- workflow: callable from inside a running event loop ----------

def test_workflow_runs_inside_running_loop():
    import asyncio

    from maverick.tools import Tool, ToolRegistry
    from maverick.workflow import Step, Workflow

    reg = ToolRegistry()
    reg.register(Tool(
        name="echo", description="echo",
        input_schema={"type": "object", "properties": {}},
        fn=lambda args: "ok",
    ))
    wf = Workflow(steps=[Step("a", "echo", {})])

    async def _driver():
        # Calling the SYNC wf.run() from inside a running loop must not
        # raise "asyncio.run() cannot be called from a running event loop".
        return wf.run(reg)

    result = asyncio.run(_driver())
    assert not result.failed
    assert result.steps[0].output == "ok"


def test_workflow_still_runs_without_loop():
    from maverick.tools import Tool, ToolRegistry
    from maverick.workflow import Step, Workflow
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo", description="echo",
        input_schema={"type": "object", "properties": {}},
        fn=lambda args: "sync-ok",
    ))
    res = Workflow(steps=[Step("a", "echo", {})]).run(reg)
    assert res.steps[0].output == "sync-ok"


# ---------- circuit breaker: honor explicit reconfig on existing key ----

def test_circuit_breaker_reconfigures_existing_key():
    from maverick.circuit_breaker import get, reset_all
    reset_all()
    first = get("svc")  # defaults: threshold 5, cooldown 30
    assert first.failure_threshold == 5
    again = get("svc", failure_threshold=2, cooldown_seconds=120)
    assert again is first  # same instance
    assert again.failure_threshold == 2  # override applied, not ignored
    assert again.cooldown_seconds == 120
    reset_all()


def test_circuit_breaker_default_get_does_not_clobber():
    from maverick.circuit_breaker import get, reset_all
    reset_all()
    get("svc2", failure_threshold=2)
    # A later default get() must NOT reset the custom threshold back to 5.
    again = get("svc2")
    assert again.failure_threshold == 2
    reset_all()


# ---------- scheduler: impossible schedule is bounded + fast ----------

def test_scheduler_impossible_schedule_raises_fast():
    from maverick.scheduler import CronError, next_run
    # Feb 30 never exists; must raise CronError quickly (day-skip walk),
    # not hang on ~2M minute iterations.
    t0 = time.time()
    raised = False
    try:
        next_run("0 0 30 2 *")
    except CronError:
        raised = True
    elapsed = time.time() - t0
    assert raised
    assert elapsed < 2.0, f"took {elapsed:.2f}s — should day-skip, not minute-walk"


def test_scheduler_leap_day_still_resolves():
    import datetime as _dt

    from maverick.scheduler import next_run
    # Feb 29 IS valid on leap years; must resolve to 2028-02-29.
    base = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc).timestamp()
    ts = next_run("0 0 29 2 *", after=base)
    got = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    assert got.month == 2 and got.day == 29


# ---------- llm_cache: row cap eviction ----------

def test_llm_cache_evicts_beyond_max_rows(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db", max_rows=3)
    # Insert 5 distinct keys; cap is 3.
    for i in range(5):
        cache.store(f"k{i}", provider="p", model="m", text=f"v{i}")
    s = cache.stats()
    assert s["entries"] <= 3, f"cap not enforced: {s['entries']} rows"


def test_llm_cache_eviction_keeps_most_used(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db", max_rows=2)
    cache.store("hot", provider="p", model="m", text="x")
    # Make "hot" the most-used so it survives eviction.
    for _ in range(5):
        cache.lookup("hot")
    cache.store("a", provider="p", model="m", text="x")
    cache.store("b", provider="p", model="m", text="x")
    cache.store("c", provider="p", model="m", text="x")
    # "hot" has the highest hit_count → must still be present.
    assert cache.lookup("hot") is not None


def test_llm_cache_unbounded_when_max_rows_zero(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db", max_rows=0)
    for i in range(20):
        cache.store(f"k{i}", provider="p", model="m", text="x")
    assert cache.stats()["entries"] == 20


# ---------- cost_router: tolerates partial health snapshot ----------

def test_cost_router_tolerates_snapshot_without_error_rate(monkeypatch):
    monkeypatch.setenv("MAVERICK_COST_ROUTING", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {})
    # Health snapshot rows missing 'error_rate' must not crash pick().
    import maverick.provider_health as ph
    monkeypatch.setattr(
        ph, "get",
        lambda: type("H", (), {"snapshot": staticmethod(
            lambda: [{"provider": "deepseek", "model": "deepseek-chat"}])})(),
    )
    from maverick.cost_router import CostSignal, pick
    spec = pick(CostSignal())
    assert spec is None or ":" in spec  # no KeyError
