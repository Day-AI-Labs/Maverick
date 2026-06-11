"""Onboarding v2: usage-derived suggestions, honest when data is thin."""
from __future__ import annotations

from maverick.onboarding_v2 import render, suggest
from maverick.world_model import WorldModel


def _world(tmp_path):
    return WorldModel(tmp_path / "world.db")


def test_not_enough_usage_returns_empty(tmp_path):
    w = _world(tmp_path)
    w.create_goal("only one", "")
    assert suggest(w) == []
    assert "not enough usage" in render(w)
    w.close()


def test_repeated_verb_suggests_templates(tmp_path):
    w = _world(tmp_path)
    for i in range(3):
        w.create_goal(f"research topic {i}", "")
    out = suggest(w)
    assert any("research" in s.observation for s in out)
    assert any("template" in s.suggestion for s in out)
    w.close()


def test_long_conversations_suggest_compaction(tmp_path):
    w = _world(tmp_path)
    for i in range(3):
        w.create_goal(f"g {i}", "")
    conv = w.get_or_create_conversation("cli", "local")
    for i in range(31):
        w.append_turn(conv.id, "user", f"turn {i}")
    out = suggest(w)
    assert any("compaction" in s.suggestion for s in out)
    w.close()


def test_repeated_failures_surface_remedy(tmp_path):
    w = _world(tmp_path)
    for i in range(3):
        gid = w.create_goal(f"task {i}", "")
        if i < 2:
            w.set_goal_status(gid, "failed",
                              result="BudgetExceeded: $9 > $5")
    out = suggest(w)
    assert any("budget exceeded" in s.observation for s in out)
    w.close()


def test_multichannel_suggests_niceties(tmp_path):
    w = _world(tmp_path)
    for i in range(3):
        w.create_goal(f"g {i}", "")
    w.get_or_create_conversation("telegram", "a")
    w.get_or_create_conversation("slack", "a")
    out = suggest(w)
    assert any("rich_render" in s.action for s in out)
    w.close()


def test_render_includes_because(tmp_path):
    w = _world(tmp_path)
    for i in range(3):
        w.create_goal(f"research {i}", "")
    out = render(w)
    assert "because:" in out and "nothing applied automatically" in out
    w.close()
