"""Tests for the model-agnostic self-improvement glue (Phases 0/1/3/4)."""
from __future__ import annotations

from maverick.self_improvement import PromotionLedger, SelfImprovementController
from maverick.self_improvement_runner import (
    build_prm_examples,
    collect_calibration,
    emit_strategy_candidate,
    review_generated_tools,
    should_retire,
)
from maverick.si_producers import ToolOutcomeTracker
from maverick.trajectory_store import TrajectoryStep


def _ctrl(tmp_path):
    return SelfImprovementController(
        frozen_fn=lambda: False, audit_fn=lambda **k: None,
        ledger=PromotionLedger(path=tmp_path / "led.json"))


# -- calibration capture ----------------------------------------------------

def test_collect_calibration_off_is_noop():
    assert collect_calibration(0.9, True, enabled_fn=lambda: False) is False


def test_collect_calibration_records_when_on(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # conftest already isolates HOME; be explicit
    assert collect_calibration(0.8, True, source="test", enabled_fn=lambda: True) is True


# -- tool retire/promote loop ----------------------------------------------

def test_should_retire_on_low_rate_with_evidence(tmp_path):
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(6):
        t.record("dud", False)
    assert should_retire("dud", t)


def test_should_not_retire_a_good_or_unproven_tool(tmp_path):
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(6):
        t.record("good", True)
    t.record("new", False)  # only 1 sample
    assert not should_retire("good", t)
    assert not should_retire("new", t)


def test_review_generated_tools_promotes_retires_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(6):
        t.record("good", True)
    for _ in range(6):
        t.record("bad", False)
    actions = review_generated_tools(
        ["good", "bad"], t, baseline_success=0.5, controller=_ctrl(tmp_path))
    assert actions["good"] == "promoted"
    assert actions["bad"] == "retire"


# -- judgment dataset builder ----------------------------------------------

class _Store:
    def __init__(self, steps):
        self._s = steps

    def iter_steps(self, *, limit=10_000):
        return iter(self._s)


def test_build_prm_examples_emits_feature_rows():
    steps = [
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=0, step=0, role="coder",
                       tool="shell", tool_succeeded=True, promise=0.6, progress=0.1),
        TrajectoryStep(ts=2.0, goal_id=1, episode_id=0, step=1, role="coder",
                       promise=None),  # no label -> skipped
    ]
    rows = build_prm_examples(_Store(steps))
    assert len(rows) == 1
    assert len(rows[0]["features"]) == 12
    assert rows[0]["promise"] == 0.6


# -- strategy candidates ----------------------------------------------------

def test_emit_strategy_prompt_and_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    vp = emit_strategy_candidate("prompt", "new system preamble", 0.5, 0.7, 6,
                                 rollback="r", controller=_ctrl(tmp_path))
    assert vp.ok and vp.rung == "prompt"
    vq = emit_strategy_candidate("policy", "route hard tasks to opus", 0.5, 0.7, 8,
                                 rollback="r", controller=_ctrl(tmp_path))
    assert vq.ok and vq.rung == "policy"
