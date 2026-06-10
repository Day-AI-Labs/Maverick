"""Achievements: derived from recorded history, unlock-once, local-only."""
from __future__ import annotations

from maverick.achievements import CATALOG, evaluate, render, unlocked
from maverick.world_model import WorldModel


def _world(tmp_path):
    return WorldModel(tmp_path / "world.db")


def test_first_goal_unlocks_once(tmp_path):
    w = _world(tmp_path)
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "done")
    store = tmp_path / "ach.json"
    fresh = evaluate(w, path=store, now=1000.0)
    assert [a.key for a in fresh] == ["first_goal"]
    assert unlocked(store) == {"first_goal": 1000.0}
    assert evaluate(w, path=store) == []  # unlock-once
    w.close()


def test_nothing_unlocks_on_empty_history(tmp_path):
    w = _world(tmp_path)
    store = tmp_path / "ach.json"
    assert evaluate(w, path=store) == []
    assert unlocked(store) == {}
    w.close()


def test_multichannel_rule(tmp_path):
    w = _world(tmp_path)
    for ch in ("telegram", "slack", "cli"):
        w.get_or_create_conversation(ch, "alice")
    fresh = evaluate(w, path=tmp_path / "a.json")
    assert "multichannel" in {a.key for a in fresh}
    w.close()


def test_deep_swarm_rule(tmp_path):
    w = _world(tmp_path)
    root = w.create_goal("root", "")
    for i in range(5):
        w.create_goal(f"sub {i}", "", parent_id=root)
    fresh = evaluate(w, path=tmp_path / "a.json")
    assert "deep_swarm" in {a.key for a in fresh}
    w.close()


def test_render_marks_earned(tmp_path):
    w = _world(tmp_path)
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "done")
    out = render(w, path=tmp_path / "a.json")
    assert "★ First flight" in out
    assert "· Operator" in out
    assert f"1/{len(CATALOG)} unlocked" in out
    w.close()


def test_store_is_0600(tmp_path):
    w = _world(tmp_path)
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "done")
    store = tmp_path / "a.json"
    evaluate(w, path=store)
    assert oct(store.stat().st_mode)[-3:] == "600"
    w.close()
