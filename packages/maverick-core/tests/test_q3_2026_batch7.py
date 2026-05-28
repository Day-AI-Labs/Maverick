"""Q3 2026 batch 7: vLLM provider, Stripe + currency + a11y tools,
persistent job queue."""
from __future__ import annotations

import json
import sys
import time
import types
from unittest.mock import MagicMock

import pytest


def _openai_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


_needs_openai = pytest.mark.skipif(
    not _openai_available(),
    reason="openai SDK extra not installed in this env",
)


# ---------- vLLM provider ----------

@_needs_openai
def test_vllm_provider_default_url(monkeypatch):
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    from maverick.providers.vllm_provider import VLLMClient
    c = VLLMClient()
    assert c.DEFAULT_MODEL == "vllm"
    assert c.base_url.endswith("/v1")


@_needs_openai
def test_vllm_provider_env_url(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://gpu-box:8000")
    monkeypatch.setenv("VLLM_API_KEY", "sekret")
    from maverick.providers.vllm_provider import VLLMClient
    c = VLLMClient()
    assert c.base_url == "http://gpu-box:8000/v1"


def test_vllm_registered_in_provider_registry():
    """Registry membership check works without instantiating."""
    from maverick.providers import KNOWN_PROVIDERS
    assert "vllm" in KNOWN_PROVIDERS


@_needs_openai
def test_vllm_provider_instantiates():
    from maverick.providers import get_provider_client
    c = get_provider_client("vllm")
    assert c.__class__.__name__ == "VLLMClient"


# ---------- Stripe tool ----------

def test_stripe_requires_op():
    from maverick.tools.stripe_tool import stripe_tool
    assert "op is required" in stripe_tool().fn({})


def test_stripe_missing_key(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    fake = types.ModuleType("httpx")
    fake.get = MagicMock()
    fake.post = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.stripe_tool import stripe_tool
    out = stripe_tool().fn({"op": "balance"})
    assert "STRIPE_SECRET_KEY" in out


def test_stripe_balance_renders(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "available": [{"amount": 12345, "currency": "usd"}],
        "pending": [{"amount": 6789, "currency": "usd"}],
    })
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.stripe_tool import stripe_tool
    out = stripe_tool().fn({"op": "balance"})
    assert "available" in out and "123.45" in out
    assert "pending" in out and "67.89" in out


def test_stripe_refund_dry_run(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock()
    fake_httpx.post = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.stripe_tool import stripe_tool
    out = stripe_tool().fn({
        "op": "refund_create", "charge_id": "ch_123",
        "amount_cents": 500,
    })
    assert "DRY RUN" in out
    # No POST was issued (still dry-run).
    fake_httpx.post.assert_not_called()


def test_stripe_refund_with_confirm(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "id": "re_xx", "amount": 500, "currency": "usd", "charge": "ch_123",
    })
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.stripe_tool import stripe_tool
    out = stripe_tool().fn({
        "op": "refund_create", "charge_id": "ch_123",
        "amount_cents": 500, "confirm": True,
    })
    assert "refunded re_xx" in out
    fake_httpx.post.assert_called_once()


def test_stripe_charges_renders(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"data": [
        {"id": "ch_1", "status": "succeeded", "amount": 1000,
         "currency": "usd", "description": "Pro plan", "refunded": False},
        {"id": "ch_2", "status": "succeeded", "amount": 500,
         "currency": "usd", "description": "addon", "refunded": True},
    ]})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.stripe_tool import stripe_tool
    out = stripe_tool().fn({"op": "charges"})
    assert "ch_1" in out and "10.00" in out
    assert "REFUNDED" in out  # ch_2 marker


# ---------- Currency tool ----------

def test_currency_requires_op():
    from maverick.tools.currency import currency
    assert "op is required" in currency().fn({})


def test_currency_convert_exchangerate(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "result": 92.345,
        "info": {"rate": 0.92345},
    })
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.currency import currency
    out = currency().fn({
        "op": "convert", "amount": 100, "from": "USD", "to": "EUR",
    })
    assert "USD = 92.3450 EUR" in out
    assert "rate" in out


def test_currency_falls_back_to_frankfurter(monkeypatch):
    """First provider returns garbage; fall back."""
    calls = {"n": 0}

    def _get(url, *a, **k):
        calls["n"] += 1
        resp = MagicMock()
        if "exchangerate" in url:
            resp.status_code = 500
            resp.json = MagicMock(side_effect=ValueError("nope"))
        else:
            resp.status_code = 200
            resp.json = MagicMock(return_value={"rates": {"JPY": 15000.0}})
        return resp

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = _get
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.currency import currency
    out = currency().fn({
        "op": "convert", "amount": 100, "from": "USD", "to": "JPY",
    })
    assert "USD = 15000.0000 JPY" in out
    assert calls["n"] == 2


def test_currency_rates_renders(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"rates": {
        "EUR": 0.92, "JPY": 150.0,
    }})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.currency import currency
    out = currency().fn({"op": "rates", "base": "USD"})
    assert "USD -> EUR" in out and "USD -> JPY" in out


# ---------- A11y tool ----------

def test_a11y_requires_op():
    from maverick.tools.a11y import a11y
    assert "op is required" in a11y().fn({})


def test_a11y_missing_runner(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.a11y import a11y
    out = a11y().fn({"op": "check", "url": "https://example.com"})
    assert "pa11y not found" in out
    assert "npm install" in out


def test_a11y_pa11y_groups_by_code(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/pa11y")
    pa11y_output = json.dumps([
        {"code": "WCAG2AA.Principle1.G18", "type": "error",
         "message": "Insufficient contrast", "selector": "#h1"},
        {"code": "WCAG2AA.Principle1.G18", "type": "error",
         "message": "Insufficient contrast", "selector": ".btn"},
        {"code": "WCAG2AA.Principle4.NoARIA", "type": "warning",
         "message": "Missing aria-label", "selector": "input"},
    ])

    def _run(cmd, *a, **k):
        return MagicMock(returncode=2, stdout=pa11y_output, stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    from maverick.tools.a11y import a11y
    out = a11y().fn({"op": "check", "url": "https://example.com"})
    assert "3 a11y issue(s)" in out
    assert "WCAG2AA.Principle1.G18  ×2" in out


def test_a11y_axe_returns_violations(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/axe")
    axe_output = json.dumps([{
        "violations": [
            {"id": "color-contrast", "impact": "serious",
             "description": "Element has insufficient contrast",
             "nodes": [{"target": "#h1"}, {"target": ".btn"}]},
        ],
    }])

    def _run(cmd, *a, **k):
        return MagicMock(returncode=0, stdout=axe_output, stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    from maverick.tools.a11y import a11y
    out = a11y().fn({"op": "check", "url": "https://example.com",
                     "runner": "axe"})
    assert "1 a11y violation" in out
    assert "color-contrast" in out and "serious" in out


# ---------- Job queue ----------

def test_job_queue_enqueue_claim_complete(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = q.enqueue("run_goal", {"goal_id": 7})
    assert jid > 0

    job = q.claim()
    assert job is not None
    assert job.kind == "run_goal"
    assert job.payload == {"goal_id": 7}
    assert job.status == "running"
    assert job.attempts == 1

    assert q.complete(jid) is True
    fetched = q.get(jid)
    assert fetched is not None
    assert fetched.status == "done"


def test_job_queue_claim_returns_none_when_empty(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    assert q.claim() is None


def test_job_queue_respects_run_at(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    future = time.time() + 60
    jid = q.enqueue("later", {}, run_at=future)
    # Nothing ready yet.
    assert q.claim() is None
    # Simulate clock moving forward.
    job = q.claim(now=future + 1)
    assert job is not None and job.id == jid


def test_job_queue_fail_reschedules(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = q.enqueue("flaky", {})
    job = q.claim()
    assert job is not None

    q.fail(jid, "transient", retry_after=0, max_attempts=3)
    j2 = q.get(jid)
    assert j2.status == "pending"
    assert j2.attempts == 1
    assert "transient" in j2.last_error

    # Re-claim works after the reschedule.
    re = q.claim()
    assert re is not None and re.id == jid
    assert re.attempts == 2


def test_job_queue_fail_terminal_after_max(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = q.enqueue("doomed", {})
    # Cycle: claim, fail with retry, claim, fail with retry, ... until max.
    for _ in range(3):
        q.claim()
        q.fail(jid, "boom", retry_after=0, max_attempts=3)
    # Next fail (now 4th attempt) should mark failed.
    q.claim()
    q.fail(jid, "boom-final", retry_after=0, max_attempts=3)
    final = q.get(jid)
    assert final.status == "failed"
    assert "boom-final" in final.last_error


def test_job_queue_list_filters_status(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    a = q.enqueue("a", {})
    b = q.enqueue("b", {})
    q.claim()  # makes one running
    pending = q.list(status="pending")
    pending_ids = {j.id for j in pending}
    # exactly one of {a,b} is still pending
    assert len(pending_ids & {a, b}) == 1


def test_job_queue_purge_removes_done(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = q.enqueue("ephemeral", {})
    q.claim()
    q.complete(jid)
    # Backdate the updated_at so purge can see it.
    import sqlite3
    with sqlite3.connect(str(q.db_path)) as c:
        c.execute(
            "UPDATE jobs SET updated_at=? WHERE id=?",
            (time.time() - 365 * 86400, jid),
        )
    deleted = q.purge(older_than_days=30)
    assert deleted == 1
    assert q.get(jid) is None


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("stripe", "currency", "a11y"):
        assert n in names, f"{n} not registered"
