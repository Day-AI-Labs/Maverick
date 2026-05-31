"""Human-in-the-loop resume flow, surfaced by dogfooding.

Before this fix, `ask_user` -> `maverick answer` -> `maverick resume` looped
forever: the resumed run never saw the answer, so the agent re-asked the same
question and re-blocked. run_goal now threads answered questions into the brief.
Also: resume must honor the configured sandbox, not silently fall back to local.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


@pytest.mark.asyncio
async def test_run_goal_threads_answered_questions_into_brief(
    tmp_path: Path, fake_llm, make_llm_response,
):
    fake_llm.scripted = [
        make_llm_response(text="FINAL: done"),
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        make_llm_response(text="FINAL: (no skill)"),
    ]
    world = WorldModel(tmp_path / "world.db")
    gid = world.create_goal("build a thing", "")
    qid = world.ask("Which language should I use?", goal_id=gid)
    world.answer(qid, "BLUEPYTHON")

    await run_goal(
        fake_llm, world, Budget(max_dollars=1.0), gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )

    # The prior question AND the user's answer reached the model, so a resumed
    # goal can act on them instead of re-asking.
    blob = "\n".join(
        f"{c.get('system', '')}{c.get('messages', '')}" for c in fake_llm.calls
    )
    assert "BLUEPYTHON" in blob
    assert "Which language should I use?" in blob


def test_resume_builds_and_passes_a_sandbox(tmp_path: Path, monkeypatch):
    import maverick.cli as cli
    import maverick.orchestrator as orch
    from click.testing import CliRunner
    from maverick.world_model import open_world

    monkeypatch.setattr(cli, "_require_llm_key", lambda: "test")
    captured: dict = {}

    def fake_run_goal_sync(llm, world, bud, goal_id, **kwargs):
        captured["sandbox"] = kwargs.get("sandbox")
        return "DONE."

    monkeypatch.setattr(orch, "run_goal_sync", fake_run_goal_sync)

    db = tmp_path / "world.db"
    w = open_world(db)
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "blocked")

    result = CliRunner().invoke(cli.main, ["--db", str(db), "resume", "--goal-id", str(gid)])
    assert result.exit_code == 0, result.output
    # resume must construct a sandbox and pass it (not rely on run_goal's
    # default), so the configured backend is honored.
    assert captured["sandbox"] is not None
