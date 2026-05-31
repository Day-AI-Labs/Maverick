"""Durable execution — Phase 1 crash-resume tests.

Covers checkpoint.py (the store + budget round-trip) and the Agent.run()
integration: a run checkpointed mid-loop resumes from the last committed step
instead of step 0, with spent budget preserved. Off-by-default is also asserted.

See docs/specs/durable-execution.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick import checkpoint as ckpt_mod
from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.llm import LLMResponse, ToolCall
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
from maverick.world_model import WorldModel


def _resp(text="", tool_calls=None, stop_reason="end_turn") -> LLMResponse:
    return LLMResponse(text=text, thinking=None,
                       tool_calls=tool_calls or [], stop_reason=stop_reason)


# ---------- store unit tests ----------

def test_checkpointer_save_and_latest(tmp_path: Path):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    cp = ckpt_mod.Checkpointer(world)
    b = Budget(max_dollars=2.0)
    b.tool_calls = 3
    b.dollars = 0.42

    assert cp.save(goal_id=gid, agent_id="orchestrator-0-abc", step_seq=2,
                   messages=[{"role": "user", "content": "hi"}], budget=b)
    got = cp.latest(gid, "orchestrator-0-abc")
    assert got is not None
    assert got.step_seq == 2
    assert got.messages == [{"role": "user", "content": "hi"}]
    assert got.budget["tool_calls"] == 3
    assert abs(got.budget["dollars"] - 0.42) < 1e-9


def test_checkpointer_latest_returns_highest_step(tmp_path: Path):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    cp = ckpt_mod.Checkpointer(world)
    for step in range(4):
        cp.save(goal_id=gid, agent_id="a", step_seq=step,
                messages=[{"role": "user", "content": str(step)}], budget=Budget())
    got = cp.latest(gid, "a")
    assert got.step_seq == 3
    assert got.messages[0]["content"] == "3"


def test_checkpointer_clear(tmp_path: Path):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    cp = ckpt_mod.Checkpointer(world)
    cp.save(goal_id=gid, agent_id="a", step_seq=0, messages=[{"x": 1}], budget=Budget())
    cp.clear(gid)
    assert cp.latest(gid, "a") is None


def test_budget_snapshot_restore_round_trip():
    b = Budget(max_dollars=7.0, max_tool_calls=99)
    b.input_tokens = 1234
    b.output_tokens = 567
    b.dollars = 1.25
    b.tool_calls = 8
    snap = ckpt_mod.snapshot_budget(b)
    r = ckpt_mod.restore_budget(snap)
    assert r.max_dollars == 7.0
    assert r.max_tool_calls == 99
    assert r.input_tokens == 1234
    assert r.output_tokens == 567
    assert r.dollars == 1.25
    assert r.tool_calls == 8
    # elapsed() continues from the snapshot, not reset to ~0.
    assert r.elapsed() >= snap["_elapsed"] - 1.0


def test_enabled_env_overrides(monkeypatch):
    monkeypatch.setenv("MAVERICK_DURABLE", "0")
    assert ckpt_mod.enabled() is False
    monkeypatch.setenv("MAVERICK_DURABLE", "1")
    assert ckpt_mod.enabled() is True


def test_enabled_default_off_without_env_or_config(monkeypatch, tmp_path):
    # No env and an empty config file -> off (the default posture).
    monkeypatch.delenv("MAVERICK_DURABLE", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text("")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    assert ckpt_mod.enabled() is False


def test_enabled_via_config(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DURABLE", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[durable]\nenabled = true\n")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    assert ckpt_mod.enabled() is True


# ---------- Agent.run() integration ----------

def _mk_ctx(tmp_path, llm):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("durable test", "")
    ctx = SwarmContext(
        llm=llm, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=gid, max_depth=1, use_skills=False,
    )
    return ctx, world, gid


class _ScriptedLLM:
    """Returns queued responses; raises if it runs past the script (so a
    'crash' is simply running out of scripted turns at a known step)."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def complete_async(self, **kwargs):
        if self.calls >= len(self._responses):
            raise RuntimeError("scripted-crash: ran past the script")
        resp = self._responses[self.calls]
        self.calls += 1
        return resp


@pytest.mark.asyncio
async def test_run_checkpoints_each_step(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_DURABLE", "1")
    # Two tool turns then crash (script exhausted on the 3rd call).
    llm = _ScriptedLLM([
        _resp(tool_calls=[ToolCall(id="t1", name="shell", input={"cmd": "echo a"})], stop_reason="tool_use"),
        _resp(tool_calls=[ToolCall(id="t2", name="shell", input={"cmd": "echo b"})], stop_reason="tool_use"),
    ])
    ctx, world, gid = _mk_ctx(tmp_path, llm)
    agent = Agent(ctx=ctx, role="researcher", brief="do it", depth=0)

    with pytest.raises(RuntimeError, match="scripted-crash"):
        await agent.run()

    # A checkpoint was committed at the turn boundary under the STABLE id
    # (not the random agent.name), keyed by the context's episode_id.
    cp = ckpt_mod.Checkpointer(world)
    saved = cp.latest(gid, agent.checkpoint_id, episode_id=ctx.episode_id)
    assert saved is not None
    assert saved.step_seq >= 1, "expected a mid-run checkpoint past step 0"


@pytest.mark.asyncio
async def test_resume_works_without_pinning_name(tmp_path, monkeypatch):
    """Production-shape resume: a FRESH agent (new random name) must resume
    from the prior checkpoint via the stable checkpoint_id — this is the bug
    Phase-1 keying had (it only worked when the test pinned agent.name)."""
    monkeypatch.setenv("MAVERICK_DURABLE", "1")
    ctx, world, gid = _mk_ctx(tmp_path, _ScriptedLLM([]))

    # Seed a checkpoint under the stable id a depth-0 researcher would use.
    b = Budget(max_dollars=1.0)
    b.tool_calls = 5
    b.dollars = 0.30
    cp = ckpt_mod.Checkpointer(world)
    cp.save(goal_id=gid, agent_id="researcher-0", episode_id=ctx.episode_id,
            step_seq=5, messages=[{"role": "user", "content": "prior work"}],
            budget=b)

    # Fresh agent — random name, NOT pinned. Resume must still match.
    llm = _ScriptedLLM([_resp(text="FINAL: resumed and done")])
    ctx.llm = llm
    agent = Agent(ctx=ctx, role="researcher", brief="do it", depth=0)
    assert agent.name != "researcher-0"  # random suffix differs

    result = await agent.run()
    assert result.final and "resumed and done" in result.final
    assert llm.calls == 1  # continued, didn't redo the 5 prior steps
    assert ctx.budget.tool_calls >= 5  # budget restored


@pytest.mark.asyncio
async def test_episode_scoping_no_cross_resume(tmp_path, monkeypatch):
    """A checkpoint under episode 1 must NOT be picked up when resuming
    episode 2 (the best-of-N safety property: same goal_id, distinct episodes)."""
    monkeypatch.setenv("MAVERICK_DURABLE", "1")
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    cp = ckpt_mod.Checkpointer(world)
    cp.save(goal_id=gid, agent_id="orchestrator-0", episode_id=1, step_seq=7,
            messages=[{"role": "user", "content": "attempt-1"}], budget=Budget())

    # Episode 2 has no checkpoint -> latest() returns None (no cross-resume).
    assert cp.latest(gid, "orchestrator-0", episode_id=2) is None
    # Episode 1 still resolves.
    got = cp.latest(gid, "orchestrator-0", episode_id=1)
    assert got is not None and got.step_seq == 7


@pytest.mark.asyncio
async def test_disabled_does_not_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_DURABLE", "0")
    llm = _ScriptedLLM([
        _resp(text="FINAL: done"),
    ])
    ctx, world, gid = _mk_ctx(tmp_path, llm)
    agent = Agent(ctx=ctx, role="researcher", brief="x", depth=0)
    result = await agent.run()
    assert result.final and "done" in result.final
    # No checkpoints table writes when disabled.
    cp = ckpt_mod.Checkpointer(world)
    assert cp.latest(gid, agent.checkpoint_id, episode_id=ctx.episode_id) is None


# ---------- Phase 2: swarm-tree (spawn_swarm) ----------

def test_clear_agent_scoped(tmp_path):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    cp = ckpt_mod.Checkpointer(world)
    cp.save(goal_id=gid, agent_id="child-A", episode_id=3, step_seq=1,
            messages=[{"x": 1}], budget=Budget())
    cp.save(goal_id=gid, agent_id="child-B", episode_id=3, step_seq=1,
            messages=[{"x": 2}], budget=Budget())
    cp.clear_agent(gid, "child-A", episode_id=3)
    assert cp.latest(gid, "child-A", episode_id=3) is None   # cleared
    assert cp.latest(gid, "child-B", episode_id=3) is not None  # sibling intact


def test_child_checkpoint_id_is_explicit_and_stable(tmp_path):
    # A spawned child gets an explicit checkpoint_id; the property returns it
    # verbatim (not the role-depth default, not the random name).
    ctx, _w, _g = _mk_ctx(tmp_path, _ScriptedLLM([]))
    child = Agent(ctx=ctx, role="researcher", brief="t", depth=1,
                  checkpoint_id="orchestrator-0.s2.0.deadbeef")
    assert child.checkpoint_id == "orchestrator-0.s2.0.deadbeef"
    # A depth-0 agent with no override falls back to role-depth.
    root = Agent(ctx=ctx, role="orchestrator", brief="t", depth=0)
    assert root.checkpoint_id == "orchestrator-0"


@pytest.mark.asyncio
async def test_spawn_swarm_child_keeps_checkpoint_on_crash_clears_on_success(tmp_path, monkeypatch):
    """A swarm with one child that finishes and one that crashes: the finished
    child's checkpoint is cleared after gather; the crashed child's is kept so
    it can resume. The parent re-runs the swarm step (Phase-2 coarse boundary),
    but each child resumes its own loop."""
    monkeypatch.setenv("MAVERICK_DURABLE", "1")

    # Per-child scripted LLMs keyed by the child's brief (task), so child A
    # finalizes immediately and child B crashes (empty script).
    scripts = {
        "task-A": _ScriptedLLM([_resp(text="FINAL: A done")]),
        "task-B": _ScriptedLLM([]),  # crashes on first call
    }

    class _RoutingLLM:
        """Routes complete_async to a per-child script based on the brief in
        the system/messages. Falls back to a finalize for the parent."""
        def __init__(self):
            self.parent_calls = 0

        async def complete_async(self, **kwargs):
            msgs = kwargs.get("messages") or []
            # Route to a child script ONLY by the child's FIRST user message
            # (its brief). The parent's later turns also mention the tasks (in
            # the spawn tool_call + results), so match messages[0] only.
            first = str(msgs[0]) if msgs else ""
            for key, script in scripts.items():
                if key in first:
                    return await script.complete_async(**kwargs)
            # Parent orchestrator turn: spawn the swarm on the first call,
            # finalize on the second.
            from maverick.llm import ToolCall as _TC
            self.parent_calls += 1
            if self.parent_calls == 1:
                return _resp(stop_reason="tool_use", tool_calls=[_TC(
                    id="s1", name="spawn_swarm",
                    input={"agents": [
                        {"role": "researcher", "task": "task-A"},
                        {"role": "researcher", "task": "task-B"},
                    ]},
                )])
            return _resp(text="FINAL: parent done")

    ctx, world, gid = _mk_ctx(tmp_path, _RoutingLLM())
    # Allow the orchestrator to spawn (depth 0 -> children at depth 1).
    object.__setattr__(ctx, "max_depth", 2)
    agent = Agent(ctx=ctx, role="orchestrator", brief="coordinate", depth=0)

    # The swarm runs; child B raises inside gather (return_exceptions=True), so
    # the parent's spawn_swarm returns a summary and the run continues.
    await agent.run()

    # There should be a kept checkpoint for the crashed child (task-B) and none
    # for the finished child (task-A).
    rows = world.conn.execute(
        "SELECT agent_id FROM checkpoints WHERE goal_id = ? AND episode_id = ?",
        (gid, ctx.episode_id),
    ).fetchall()
    ids = {r[0] for r in rows}
    kept_b = {i for i in ids if ".1." in i}   # child index 1 == task-B
    cleared_a = {i for i in ids if ".0." in i}  # child index 0 == task-A
    assert kept_b, f"crashed child B should keep a checkpoint; got {ids}"
    assert not cleared_a, f"finished child A checkpoint should be cleared; got {ids}"
