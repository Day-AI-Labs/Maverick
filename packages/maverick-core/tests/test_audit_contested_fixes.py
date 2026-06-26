"""Regression tests for three contested audit findings adjudicated as real.

c3 — a sealed (quarantined) child's attacker-influenced FINAL was emitted to
     SUBAGENT_STOP hooks before the withhold check (tools/spawn.py).
c4 — A2A task-failure artifacts carried the unscrubbed exception text to the
     caller and the push webhook (a2a_tasks.py).
c5 — scrub_env() missed PASSPHRASE / NETRC / COOKIE / AUTH credential vars
     (sandbox/local.py).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.domain import enabled_domains
from maverick.quarantine import QuarantineRegistry
from maverick.tools.spawn import spawn_specialist_tool


def test_scrub_env_strips_passphrase_netrc_cookie_auth():
    from maverick.sandbox.local import scrub_env
    src = {
        "ANSIBLE_VAULT_PASSPHRASE": "p",
        "NETRC": "/root/.netrc",
        "SESSION_COOKIE": "abc",
        "GITHUB_AUTH": "tok",
        "PATH": "/usr/bin",
        "HOME": "/home/u",
    }
    out = scrub_env(src)
    for leaked in ("ANSIBLE_VAULT_PASSPHRASE", "NETRC", "SESSION_COOKIE", "GITHUB_AUTH"):
        assert leaked not in out, leaked
    assert out["PATH"] == "/usr/bin" and out["HOME"] == "/home/u"


def test_a2a_task_failure_scrubs_exception_text():
    from maverick import a2a_tasks
    from maverick.secrets import scrub
    task = a2a_tasks._Task(
        "ctx", {"role": "user", "parts": [], "messageId": "m", "kind": "message"})
    # Mirror the fixed failure path: a connection error carrying a DSN secret.
    e = RuntimeError("connect failed: postgres://user:supersecretpw@db/app")
    detail = scrub(f"{type(e).__name__}: {e}")
    task.add_artifact(f"task failed: {detail}", "error")
    # The task dict is what reaches the caller and the push webhook.
    assert "supersecretpw" not in str(task.to_dict())


def _fake_parent(depth=0):
    ctx = SimpleNamespace(
        budget=Budget(max_dollars=10.0), blackboard=Blackboard(), max_depth=3,
        goal_id=1, quarantine=None,
        try_reserve_spawns=lambda n: True, release_spawns=lambda n: None,
    )
    return SimpleNamespace(depth=depth, name="orchestrator", role="orchestrator",
                           ctx=ctx, max_steps=17, capability=None)


@pytest.mark.asyncio
async def test_sealed_mid_run_child_final_not_leaked_into_subagent_stop_hook(monkeypatch):
    # The leak path is a child sealed DURING run: the spawn-time check passes
    # (not yet sealed), the child runs and is compromised, then the post-run
    # check withholds it -- but the SUBAGENT_STOP hook fired in between with the
    # raw final. The fix moves the withhold check above the emit.
    dom = sorted(enabled_domains())[0]
    quarantine = QuarantineRegistry()
    parent = _fake_parent()
    parent.ctx.quarantine = quarantine

    def fake_agent_from_profile(profile, ctx, task, *, parent=None, depth=0, principal=None):
        name = f"agent:{profile.name}-{depth}"

        async def _run():
            quarantine.seal(name, "compromised mid-run")  # sealed AFTER spawn check
            return SimpleNamespace(final="SHOULD NOT LEAK", blocked_on_user=False, error=None)
        return SimpleNamespace(role=profile.name, name=name,
                               domain=profile.compartment, max_steps=None, run=_run)

    captured = {}

    async def _capture_hook(event, **kwargs):
        captured["final"] = (kwargs.get("extra") or {}).get("final")

    monkeypatch.setattr("maverick.domain.agent_from_profile", fake_agent_from_profile)
    monkeypatch.setattr("maverick.hooks.emit", _capture_hook)

    out = await spawn_specialist_tool(parent).fn({"domain": dom, "task": "do it"})
    assert "SHOULD NOT LEAK" not in out
    # The hook payload must NOT carry the sealed child's raw final either.
    assert captured.get("final") is not None
    assert "SHOULD NOT LEAK" not in captured["final"]
    assert "withheld" in captured["final"]
