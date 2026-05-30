"""run_goal must emit outbound webhooks at run lifecycle boundaries.

webhooks.fire() was fully implemented but had zero callers. The
orchestrator now fires goal_created / episode_finished / final_emitted /
goal_finished at the matching points in run_goal. fire() is a silent
no-op when no [webhooks] outbound is configured, so we monkeypatch it to
record the calls instead of standing up a transport.

Style mirrors test_orchestrator_output_scan.py: a real in-memory
WorldModel + the fake_llm/make_llm_response fixtures, run_goal to
completion.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


@pytest.mark.asyncio
async def test_run_goal_fires_lifecycle_webhooks(
    tmp_path: Path, fake_llm, make_llm_response, monkeypatch,
):
    # No shield in the way; we only care about webhook emission.
    monkeypatch.setattr("maverick.orchestrator._build_shield", lambda: None)

    calls: list[tuple[str, dict]] = []
    # _fire_webhook imports fire from maverick.webhooks at call time, so
    # patching the function on the module is enough -- no transport needed.
    monkeypatch.setattr(
        "maverick.webhooks.fire",
        lambda event, payload, **kw: calls.append((event, payload)) or 0,
    )

    fake_llm.scripted = [
        make_llm_response(text="FINAL: the answer is 42"),
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        make_llm_response(text="FINAL: (no skill)"),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("compute the answer", "trivial")

    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )

    events = [e for e, _ in calls]
    assert "goal_created" in events
    assert "episode_finished" in events
    assert "final_emitted" in events
    assert "goal_finished" in events

    # goal_finished carries the terminal status + goal id.
    finished = next(p for e, p in calls if e == "goal_finished")
    assert finished["goal_id"] == gid
    assert finished["status"] == "done"

    # goal_created carries id + title; episode_finished carries the outcome.
    created = next(p for e, p in calls if e == "goal_created")
    assert created["goal_id"] == gid
    assert created["title"] == "compute the answer"

    episode = next(p for e, p in calls if e == "episode_finished")
    assert episode["goal_id"] == gid
    assert episode["outcome"] == "success"
