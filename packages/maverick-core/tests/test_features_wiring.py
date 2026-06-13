"""The [features] config section actually gates behavior.

These keys were documented in configuration.md but nothing read them:
  - skills      -> inject skills into agent prompts (env var still overrides)
  - world_model -> inject persisted facts (cross-run memory) into runs
  - streaming   -> live progress poller (covered by the config getter test;
                   the poller branch also depends on TTY/MAVERICK_NO_PROGRESS)
  - pack_editing-> allow editing/overriding agents (domain packs) from the
                   dashboard editor (mutating /api/v1/agents endpoints)
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------- config.get_features ----------

def test_get_features_defaults_all_on(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("")  # no [features] section at all
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    from maverick.config import get_features
    assert get_features() == {
        "skills": True, "world_model": True, "streaming": True, "pack_editing": True,
    }


def test_get_features_reads_overrides(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[features]\nskills = false\nworld_model = false\nstreaming = false\n"
        "pack_editing = false\n"
    )
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    from maverick.config import get_features
    assert get_features() == {
        "skills": False, "world_model": False, "streaming": False, "pack_editing": False,
    }


# ---------- swarm._default_use_skills precedence ----------

def test_use_skills_env_wins_over_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[features]\nskills = false\n")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    from maverick.swarm import _default_use_skills
    # env explicitly on -> on, despite config saying off
    monkeypatch.setenv("MAVERICK_USE_SKILLS", "1")
    assert _default_use_skills() is True
    # env explicitly off -> off
    monkeypatch.setenv("MAVERICK_USE_SKILLS", "0")
    assert _default_use_skills() is False


def test_use_skills_falls_back_to_config_when_env_unset(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[features]\nskills = false\n")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    monkeypatch.delenv("MAVERICK_USE_SKILLS", raising=False)
    from maverick.swarm import _default_use_skills
    assert _default_use_skills() is False


def test_use_skills_default_on_when_nothing_set(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    monkeypatch.delenv("MAVERICK_USE_SKILLS", raising=False)
    from maverick.swarm import _default_use_skills
    assert _default_use_skills() is True


# ---------- world_model gates persisted-fact injection ----------

async def _run_capturing_brief(tmp_path, fake_llm, monkeypatch, *, world_model: bool):
    from maverick.budget import Budget
    from maverick.orchestrator import run_goal
    from maverick.sandbox import LocalBackend
    from maverick.world_model import WorldModel

    # Isolate from the shield (the fact loop would otherwise scan each fact).
    monkeypatch.setattr("maverick.orchestrator._build_shield", lambda: None)
    monkeypatch.setattr(
        "maverick.config.get_features",
        lambda: {"skills": True, "world_model": world_model, "streaming": True},
    )
    world = WorldModel(path=tmp_path / "world.db")
    world.upsert_fact("favorite_color", "chartreuse")
    gid = world.create_goal("say hi", "trivial")
    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )
    # The orchestrator brief (which carries the facts block) is passed as the
    # task message, not the system prompt -- capture the whole call.
    return "\n".join(str(c) for c in fake_llm.calls)


@pytest.mark.asyncio
async def test_world_model_on_injects_facts(tmp_path: Path, fake_llm, monkeypatch):
    briefs = await _run_capturing_brief(tmp_path, fake_llm, monkeypatch, world_model=True)
    assert "chartreuse" in briefs


@pytest.mark.asyncio
async def test_world_model_off_drops_facts(tmp_path: Path, fake_llm, monkeypatch):
    briefs = await _run_capturing_brief(tmp_path, fake_llm, monkeypatch, world_model=False)
    assert "chartreuse" not in briefs
