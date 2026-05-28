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


# ---------- observability: record_metric label handling ----------

def test_record_metric_unlabeled_gauge_no_crash(monkeypatch):
    import maverick.observability as obs

    calls = {"set": None}

    class _Gauge:
        def inc(self, _v):
            raise AssertionError("gauge must not use inc() for absolute values")

        def set(self, v):
            calls["set"] = v

        def labels(self, **kw):
            raise AssertionError("must not call .labels() with no labels")

    monkeypatch.setattr(obs, "_metrics", {"budget_dollars": _Gauge()})
    monkeypatch.setattr(obs, "_initialize", lambda: None)
    obs.record_metric("budget_dollars", 1.23)  # no labels
    assert calls["set"] == 1.23


def test_record_metric_labeled_counter(monkeypatch):
    import maverick.observability as obs

    seen = {"labels": None, "inc": None}

    class _Child:
        def inc(self, v):
            seen["inc"] = v

    class _Counter:
        def labels(self, **kw):
            seen["labels"] = kw
            return _Child()

    monkeypatch.setattr(obs, "_metrics", {"llm_calls": _Counter()})
    monkeypatch.setattr(obs, "_initialize", lambda: None)
    obs.record_metric("llm_calls", 1.0,
                      labels={"provider": "anthropic", "model": "m"})
    assert seen["labels"] == {"provider": "anthropic", "model": "m"}
    assert seen["inc"] == 1.0


def test_prometheus_exporter_defaults_to_loopback_bind(monkeypatch):
    import importlib
    import sys
    import types

    monkeypatch.setenv("MAVERICK_PROMETHEUS_PORT", "9999")
    monkeypatch.delenv("MAVERICK_PROMETHEUS_ADDR", raising=False)
    monkeypatch.delenv("MAVERICK_OTEL_EXPORTER", raising=False)

    calls = {}

    def _start_http_server(port, *args, **kwargs):
        calls["port"] = port
        calls["args"] = args
        calls["kwargs"] = kwargs

    fake_prom = types.SimpleNamespace(
        Counter=lambda *a, **k: object(),
        Gauge=lambda *a, **k: object(),
        Histogram=lambda *a, **k: object(),
        start_http_server=_start_http_server,
    )
    monkeypatch.setitem(sys.modules, "prometheus_client", fake_prom)

    import maverick.observability as obs
    obs = importlib.reload(obs)
    monkeypatch.setattr(obs, "_initialized", False)
    monkeypatch.setattr(obs, "_metrics", {})
    obs._initialize()

    assert calls["port"] == 9999
    assert calls["kwargs"].get("addr") == "127.0.0.1"


# ---------- chaos: concurrent roll() doesn't tear the RNG ----------

def test_chaos_roll_is_thread_safe_smoke():
    import threading

    from maverick.chaos import ChaosController, ChaosInjected, maybe_fail
    c = ChaosController()
    c.set(active=True, seed=1, sandbox_exec_fail_pct=50)
    errors: list[str] = []

    def _hammer():
        for _ in range(200):
            try:
                maybe_fail("sandbox_exec")
            except ChaosInjected:
                pass
            except Exception as e:  # a torn RNG read would land here
                errors.append(repr(e))

    threads = [threading.Thread(target=_hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.disable()
    assert not errors, f"concurrent roll() raised: {errors[:3]}"


# ---------- sandbox: timeout cleanup never masks the TIMEOUT result ----

def test_podman_timeout_cleanup_swallows_cleanup_error(monkeypatch, tmp_path):
    import subprocess

    from maverick.sandbox.podman import PodmanBackend

    def _run(args, *a, **k):
        if args[:2] == ["podman", "version"]:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        if args[:2] == ["podman", "rm"]:
            # Cleanup itself blows up — must be swallowed.
            raise subprocess.TimeoutExpired(cmd="podman rm", timeout=10)
        # The actual `podman run` times out.
        raise subprocess.TimeoutExpired(cmd="podman run", timeout=5)

    monkeypatch.setattr("subprocess.run", _run)
    backend = PodmanBackend(workdir=tmp_path, image="alpine")
    result = backend.exec("sleep 999")
    assert result.exit_code == 124
    assert "TIMEOUT" in result.stderr


# ---------- audit signing: tampered rows flagged, not crashed ----------

def _crypto_available() -> bool:
    try:
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
        return True
    except BaseException:
        return False


def test_audit_verify_flags_nonhex_sig_instead_of_crashing(tmp_path, monkeypatch):
    if not _crypto_available():
        return
    import json as _json

    from maverick.audit import signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    path = tmp_path / "audit.ndjson"
    s = signing.AuditSigner(path)
    s.write({"event": "a"})
    s.write({"event": "b"})
    # Corrupt line 1's sig to a non-hex string.
    lines = path.read_text().splitlines()
    row = _json.loads(lines[0])
    row["sig"] = "zzzz-not-hex"
    lines[0] = _json.dumps(row)
    path.write_text("\n".join(lines) + "\n")
    # Must return a ChainBreak (not raise), and still check later rows.
    breaks = signing.verify_chain(path)
    assert breaks  # did not crash
    assert any(b.reason == "bad_signature" for b in breaks)


def test_audit_verify_rejects_lone_pubkey(tmp_path, monkeypatch):
    """A .pub with no sibling .key (attacker-dropped) is not trusted."""
    if not _crypto_available():
        return
    import json as _json

    from maverick.audit import signing
    keydir = tmp_path / "keys"
    monkeypatch.setattr(signing, "KEY_DIR", keydir)
    path = tmp_path / "audit.ndjson"
    s = signing.AuditSigner(path)
    s.write({"event": "a"})
    # Remove the private key, leaving only the .pub (simulating a
    # verifier host that only has a dropped pubkey).
    for keyfile in keydir.glob("*.key"):
        keyfile.unlink()
    breaks = signing.verify_chain(path)
    assert any(b.reason == "no_pubkey" for b in breaks)
    _ = _json  # silence



def test_audit_verify_rejects_path_traversal_key_id(tmp_path, monkeypatch):
    if not _crypto_available():
        return
    import json as _json

    from maverick.audit import signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    path = tmp_path / "audit.ndjson"
    s = signing.AuditSigner(path)
    s.write({"event": "a"})

    lines = path.read_text().splitlines()
    row = _json.loads(lines[0])
    row["key_id"] = "../../tmp/evil"
    lines[0] = _json.dumps(row)
    path.write_text("\n".join(lines) + "\n")

    breaks = signing.verify_chain(path)
    assert any(b.reason == "no_pubkey" for b in breaks)


# ---------- hackernews: null points on comment hits ----------

def test_hackernews_handles_null_points(monkeypatch):
    body = {"hits": [
        {"title": None, "comment_text": "a comment", "points": None,
         "objectID": "42"},
    ]}
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=body)
    _fake_httpx(monkeypatch, get=MagicMock(return_value=resp))
    from maverick.tools.hackernews import hackernews
    out = hackernews().fn({"op": "search", "query": "x"})
    assert "ERROR" not in out


# ---------- calendar find_slot: latest_hour=23 must not crash ----------

def test_calendar_find_slot_latest_hour_23(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", "https://cal.test")
    monkeypatch.setenv("CALDAV_USER", "me@test")
    monkeypatch.setenv("CALDAV_PASSWORD", "pw")
    import sys as _sys
    import types as _types
    fake_caldav = _types.ModuleType("caldav")
    fake_calendar = MagicMock()
    fake_calendar.search = MagicMock(return_value=[])
    fake_principal = MagicMock()
    fake_principal.calendars = MagicMock(return_value=[fake_calendar])
    fake_client = MagicMock()
    fake_client.principal = MagicMock(return_value=fake_principal)
    fake_caldav.DAVClient = MagicMock(return_value=fake_client)
    monkeypatch.setitem(_sys.modules, "caldav", fake_caldav)
    from maverick.tools.calendar_tool import calendar_tool
    # earliest=23, latest=23 — previously max(24, min(23,23))=24 →
    # cursor.replace(hour=24) ValueError. Must not crash now.
    out = calendar_tool().fn({
        "op": "find_slot", "earliest_hour": 23, "latest_hour": 23,
    })
    assert "hour must be in 0..23" not in out
    assert "ValueError" not in out


# ---------- compute fallback: power-tower CPU/memory DoS ----------

def test_compute_fallback_blocks_power_tower(monkeypatch):
    import sys as _sys
    # Force the no-sympy fallback path.
    monkeypatch.setitem(_sys.modules, "sympy", None)
    from maverick.tools.compute import compute
    out = compute().fn({"op": "evaluate", "expr": "9**9**9"})
    assert "ERROR" in out  # blocked, not a 370M-digit hang
    ok = compute().fn({"op": "evaluate", "expr": "2**8"})
    assert "256" in ok


# ---------- replay_export: non-numeric goal_id skips, not crashes ----

def test_replay_export_skips_bad_goal_id(tmp_path, monkeypatch):
    import json as _json

    import maverick.replay_export as rex
    audit = tmp_path / "audit"
    audit.mkdir()
    f = audit / "2026-05-28.ndjson"
    rows = [
        {"goal_id": 7, "kind": "goal_start"},
        {"goal_id": "not-a-number", "kind": "junk"},  # must not abort
        {"goal_id": 7, "kind": "goal_end"},
    ]
    f.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(rex, "_AUDIT_DIR", audit)
    out_file = tmp_path / "r.json"
    n = rex.export_json(7, out_file)
    assert n == 2  # both goal-7 rows survived; the bad row was skipped


# ---------- retention: only the known tables are purgeable ----------

def test_retention_rejects_unknown_table(tmp_path):
    import sqlite3

    from maverick.audit.retention import _purge_table_by_time
    db = tmp_path / "w.db"
    sqlite3.connect(str(db)).close()
    try:
        _purge_table_by_time(db, "goals; DROP TABLE goals", "x", 0.0, dry_run=True)
    except ValueError as e:
        assert "unknown table/column" in str(e)
        return
    raise AssertionError("expected ValueError on non-whitelisted table")


def test_retention_allows_known_table(tmp_path):
    import sqlite3

    from maverick.audit.retention import _purge_table_by_time
    db = tmp_path / "w.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE episodes (id INTEGER, ended_at REAL)")
    c.execute("INSERT INTO episodes VALUES (1, 100.0)")
    c.commit()
    c.close()
    removed = _purge_table_by_time(db, "episodes", "ended_at", 200.0, dry_run=True)
    assert removed == 1  # dry run counts the old row, doesn't delete


# ---------- verifier: fail CLOSED on LLM error ----------

def test_verifier_fails_closed_on_llm_error():
    import asyncio

    from maverick.budget import Budget
    from maverick.verifier import verify_proposal

    class _Boom:
        async def complete_async(self, **kw):
            raise RuntimeError("provider down")

    v = asyncio.run(verify_proposal("brief", "some proposal", _Boom(), Budget()))
    # Contract: any failure -> reject (NOT the old accepts=True fail-open).
    assert v.accepts is False


def test_verifier_propagates_budget_exceeded():
    import asyncio

    from maverick.budget import Budget, BudgetExceeded
    from maverick.verifier import verify_proposal

    class _OverBudget:
        async def complete_async(self, **kw):
            raise BudgetExceeded("$5 > $5")

    try:
        asyncio.run(verify_proposal("brief", "p", _OverBudget(), Budget()))
    except BudgetExceeded:
        return  # budget is a control signal, must propagate
    raise AssertionError("expected BudgetExceeded to propagate")


# ---------- edit_format: fuzzy match safety ----------

def test_edit_format_indent_match_slice_actually_matches():
    """When step 3 returns an indent_norm match, the mapped-back slice
    must really indent-match the needle (the recheck guard)."""
    from maverick.edit_format import _find_with_fuzzy, _normalise_indent
    content = (
        "def a():\n"
        "    x = 1\n"
        "    return x\n"
        "\n"
        "class C:\n"
        "    def a(self):\n"
        "        y = 2\n"
        "        return y\n"
    )
    needle = "x = 1\nreturn x\n"  # uniquely indent-matches the first block
    start, end, strategy = _find_with_fuzzy(content, needle)
    assert start is not None
    needle_ni, _ = _normalise_indent(needle)
    assert _normalise_indent(content[start:end])[0].startswith(needle_ni)


def test_edit_format_refuses_two_identical_blocks():
    """Two byte-identical blocks → fuzzy tiers must refuse (ambiguous),
    never silently pick the first."""
    from maverick.edit_format import _find_with_fuzzy
    content = "    x = 1\n    return x\n\n    x = 1\n    return x\n"
    needle = "x = 1\nreturn x\n"
    start, end, strategy = _find_with_fuzzy(content, needle)
    assert strategy == "ambiguous"
    assert start is None and end is None
