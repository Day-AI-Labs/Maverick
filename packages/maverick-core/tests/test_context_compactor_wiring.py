"""Context compaction, wired into the orchestrator's conversation history.

context_compactor.compact existed but nothing called it. The orchestrator
now optionally pulls a larger window of prior turns and compacts it to a
token budget (keeping the most relevant older turns) instead of always
including just the last 10. Opt-in via MAVERICK_COMPACT_HISTORY=1 or
[context] compact = true; off by default.
"""
from __future__ import annotations

from pathlib import Path

import maverick.config as cfg
import pytest
from maverick import context_compactor as cc
from maverick.budget import Budget
from maverick.llm import LLMResponse
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel

# ---------- config helpers ----------

class TestCompactorConfig:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_COMPACT_HISTORY", raising=False)
        monkeypatch.setattr(cfg, "load_config", lambda: {})
        assert cc.enabled() is False

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_COMPACT_HISTORY", "1")
        assert cc.enabled() is True

    def test_enabled_via_config(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_COMPACT_HISTORY", raising=False)
        monkeypatch.setattr(cfg, "load_config", lambda: {"context": {"compact": True}})
        assert cc.enabled() is True

    def test_target_tokens_and_window(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_HISTORY_TOKENS", raising=False)
        monkeypatch.delenv("MAVERICK_HISTORY_WINDOW", raising=False)
        monkeypatch.setattr(cfg, "load_config", lambda: {})
        assert cc.target_tokens() == 1500
        assert cc.window() == 50
        monkeypatch.setenv("MAVERICK_HISTORY_TOKENS", "200")
        monkeypatch.setenv("MAVERICK_HISTORY_WINDOW", "0")  # clamp to >= 1
        assert cc.target_tokens() == 200
        assert cc.window() == 50
        monkeypatch.delenv("MAVERICK_HISTORY_TOKENS", raising=False)
        monkeypatch.setattr(cfg, "load_config", lambda: {"context": {"history_tokens": 99}})
        assert cc.target_tokens() == 99


# ---------- orchestrator wiring ----------

def _prompt_blob(fake_llm) -> str:
    blob = ""
    for c in fake_llm.calls:
        blob += c.get("system") or ""
        for m in (c.get("messages") or []):
            blob += str(m.get("content", ""))
    return blob


def _seed_conversation(world, n=30):
    conv = world.get_or_create_conversation("tg", "u1")
    for i in range(n):
        world.append_turn(
            conv.id, "user" if i % 2 == 0 else "assistant",
            f"message number {i} about deploying the parser service",
        )
    return conv


@pytest.mark.asyncio
async def test_long_history_is_compacted_when_enabled(monkeypatch, tmp_path: Path, fake_llm):
    monkeypatch.setenv("MAVERICK_COMPACT_HISTORY", "1")
    monkeypatch.setenv("MAVERICK_HISTORY_TOKENS", "80")   # small -> forces a drop
    monkeypatch.setenv("MAVERICK_HISTORY_WINDOW", "40")

    world = WorldModel(path=tmp_path / "world.db")
    conv = _seed_conversation(world, n=30)
    gid = world.create_goal("Continue the deploy", "")
    fake_llm.scripted = [
        LLMResponse(text="FINAL: done", thinking=None, stop_reason="end_turn", tool_calls=[]),
    ]

    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
        conversation_id=conv.id,
    )
    assert "compacted to save context" in _prompt_blob(fake_llm)  # compaction ran


@pytest.mark.asyncio
async def test_history_uses_last_10_when_disabled(monkeypatch, tmp_path: Path, fake_llm):
    monkeypatch.delenv("MAVERICK_COMPACT_HISTORY", raising=False)
    monkeypatch.setattr(cfg, "load_config", lambda: {})

    world = WorldModel(path=tmp_path / "world.db")
    conv = _seed_conversation(world, n=30)
    gid = world.create_goal("Continue the deploy", "")
    fake_llm.scripted = [
        LLMResponse(text="FINAL: done", thinking=None, stop_reason="end_turn", tool_calls=[]),
    ]

    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
        conversation_id=conv.id,
    )
    blob = _prompt_blob(fake_llm)
    assert "compacted to save context" not in blob   # no compaction
    assert "message number 29" in blob               # last turn included
    assert "message number 0 about" not in blob       # turn 0 dropped (only last 10)
