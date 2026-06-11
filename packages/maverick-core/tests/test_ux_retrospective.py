"""UX retrospective: period aggregation + honest empty sections."""
from __future__ import annotations

import time

from maverick.ux_retrospective import collect, render
from maverick.world_model import WorldModel


def _world(tmp_path):
    return WorldModel(tmp_path / "world.db")


def test_collect_aggregates_goals_channels(tmp_path):
    w = _world(tmp_path)
    for title in ("research the market", "research competitors", "fix the bug"):
        w.create_goal(title, "")
    w.get_or_create_conversation("telegram", "alice")
    w.get_or_create_conversation("slack", "bob")
    w.get_or_create_conversation("telegram", "carol")
    now = time.time()
    data = collect(w, now - 3600, now + 3600)
    assert data["goals"]["total"] == 3
    assert data["goals"]["by_verb"]["research"] == 2
    assert data["channels"] == {"telegram": 2, "slack": 1}
    w.close()


def test_window_excludes_out_of_range(tmp_path):
    w = _world(tmp_path)
    w.create_goal("old goal", "")
    # a window entirely in the past excludes the just-created goal
    data = collect(w, 1000.0, 2000.0)
    assert data["goals"]["total"] == 0
    w.close()


def test_render_with_data(tmp_path):
    w = _world(tmp_path)
    w.create_goal("research things", "")
    now = time.time()
    out = render(collect(w, now - 60, now + 60))
    assert "goals in window: 1" in out
    assert "research (1)" in out
    assert "Reset worksheet" in out
    w.close()


def test_render_empty_sections_say_so(tmp_path):
    w = _world(tmp_path)
    now = time.time()
    out = render(collect(w, now - 60, now + 60))
    assert "no recorded usage in this window" in out
    assert "no channel conversations recorded" in out
    assert "no approval decisions recorded" in out
    w.close()
