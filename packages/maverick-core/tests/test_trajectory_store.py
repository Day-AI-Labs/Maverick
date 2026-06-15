"""Tests for governed trajectory capture (Phase 0 data foundation)."""
from __future__ import annotations

from maverick.trajectory_store import (
    TrajectoryStep,
    TrajectoryStore,
    capture_step,
    reset_shared,
)


def _step(**kw):
    base = dict(ts=1.0, goal_id=7, episode_id=1, step=0, role="coder")
    base.update(kw)
    return TrajectoryStep(**base)


def test_capture_off_by_default_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_TRAJECTORY_CAPTURE", raising=False)
    reset_shared()
    assert capture_step(_step()) is False


def test_record_and_iter_roundtrip(tmp_path):
    store = TrajectoryStore(path=tmp_path / "t.ndjson")
    assert store.record(_step(step=0, tool="read_file", tool_succeeded=True))
    assert store.record(_step(step=1, tool="shell", tool_succeeded=False, error="boom"))
    steps = list(store.iter_steps(goal_id=7))
    assert len(steps) == 2
    assert steps[0].tool == "read_file"
    assert steps[1].tool_succeeded is False


def test_secrets_are_redacted_before_disk(tmp_path):
    secret = "sk-ant-" + "a" * 30  # pragma: allowlist secret  (fabricated test fixture)
    store = TrajectoryStore(path=tmp_path / "t.ndjson")
    store.record(_step(error=f"failed with key {secret}"))
    raw = (tmp_path / "t.ndjson").read_text(encoding="utf-8")
    assert secret not in raw  # scrubbed
    assert "goal_id" in raw   # but the row is still there


def test_goal_filter_and_count(tmp_path):
    store = TrajectoryStore(path=tmp_path / "t.ndjson")
    store.record(_step(goal_id=7))
    store.record(_step(goal_id=8))
    assert store.count() == 2
    assert len(list(store.iter_steps(goal_id=7))) == 1


def test_rotation_bounds_the_file(tmp_path):
    store = TrajectoryStore(path=tmp_path / "t.ndjson", max_rows=10)
    for i in range(25):
        store.record(_step(step=i))
    assert store.count() <= 10


def test_capture_step_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_TRAJECTORY_CAPTURE", "1")
    store = TrajectoryStore(path=tmp_path / "t.ndjson")
    assert capture_step(_step(), store=store) is True
    assert store.count() == 1
