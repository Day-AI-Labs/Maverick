"""Per-tenant daily-spend cap on the CORE run path (#74), plan-cap fallback
(#81), and loud fail-soft spend reads (#77).

The channel door already enforced the per-tenant cap; dashboard/CLI/gRPC runs
bypass that door, so run_goal must enforce it too. All opt-in: a tenant cap only
exists once provisioned (or under [billing] enforce_plan_caps). Hermetic,
mirroring test_quota_enforcement.py (FakeLLM + tmp world db + LocalBackend)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.quotas import record_usage
from maverick.sandbox import LocalBackend
from maverick.tenant import registry
from maverick.world_model import WorldModel


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / ".maverick"))
    for env in ("MAVERICK_QUOTA_ENFORCE", "MAVERICK_TENANT",
                "MAVERICK_ENFORCE_PLAN_CAPS"):
        monkeypatch.delenv(env, raising=False)


def _final_script(make_llm_response):
    return [
        make_llm_response(text="FINAL: the answer is 42"),
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}'),
        make_llm_response(text="FINAL: (no skill)"),
    ]


@pytest.mark.asyncio
async def test_over_tenant_quota_refuses_on_core_run_path(
    tmp_path: Path, fake_llm, make_llm_response, monkeypatch,
):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 5.0)
    record_usage("user:local", 10.0, 0, 0)  # lands in acme's ledger -> over $5

    fake_llm.scripted = _final_script(make_llm_response)
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("compute the answer", "trivial")

    out = await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0), goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )
    assert "spend cap" in out
    assert fake_llm.calls == []                       # refused before the LLM ran
    goal = world.get_goal(gid)
    assert goal.status == "blocked"
    assert "quota" in (goal.result or "")             # result is "over quota: ..."


@pytest.mark.asyncio
async def test_tenant_without_a_cap_runs(
    tmp_path: Path, fake_llm, make_llm_response, monkeypatch,
):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")        # provisioned, no quota set
    record_usage("user:local", 10.0, 0, 0)

    fake_llm.scripted = _final_script(make_llm_response)
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("compute the answer", "trivial")

    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0), goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )
    assert world.get_goal(gid).status != "blocked"
    assert fake_llm.calls                              # the LLM ran (no cap)


def test_plan_cap_fallback_is_opt_in(monkeypatch):
    registry.create_tenant("beta", plan="free")        # free plan cap = $5, no registry cap
    monkeypatch.setenv("MAVERICK_TENANT", "beta")
    record_usage("user:local", 9.0, 0, 0)              # beta's ledger -> $9
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    assert registry.tenant_over_quota("beta") is None  # off by default -> no cap
    monkeypatch.setenv("MAVERICK_ENFORCE_PLAN_CAPS", "1")
    assert registry.tenant_over_quota("beta") is not None  # now uses the plan cap


def test_spend_read_warns_on_unreadable_ledger(monkeypatch, caplog):
    registry.create_tenant("gamma", plan="free")
    from maverick import quotas

    def _boom(self):
        raise OSError("corrupt ledger")
    monkeypatch.setattr(quotas.UsageLedger, "_load", _boom)
    with caplog.at_level(logging.WARNING):
        assert registry.tenant_spend_today("gamma") == 0.0   # fail-soft
    assert any("unreadable usage ledger" in r.getMessage() for r in caplog.records)
