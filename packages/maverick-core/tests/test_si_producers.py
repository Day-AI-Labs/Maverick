"""Tests for the per-rung self-improvement producers (Phases 1-6 -> one gate)."""
from __future__ import annotations

from maverick.self_improvement import SelfImprovementController, PromotionLedger
from maverick.si_producers import (
    ToolOutcomeTracker,
    propose_code,
    propose_policy,
    propose_tool,
    propose_verifier,
    propose_weights,
)


def _ctrl(tmp_path):
    return SelfImprovementController(
        frozen_fn=lambda: False, audit_fn=lambda **k: None,
        ledger=PromotionLedger(path=tmp_path / "led.json"),
    )


# -- Phase 3: tool outcome tracker + promotion -----------------------------

def test_tool_tracker_counts_and_rate(tmp_path):
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(4):
        t.record("mk_tool", True)
    t.record("mk_tool", False)
    assert t.samples("mk_tool") == 5
    assert abs(t.success_rate("mk_tool") - 0.8) < 1e-9


def test_tool_tracker_persists(tmp_path):
    p = tmp_path / "to.json"
    ToolOutcomeTracker(path=p).record("x", True)
    assert ToolOutcomeTracker(path=p).samples("x") == 1


def test_propose_tool_promotes_when_it_beats_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(6):
        t.record("good_tool", True)
    v = propose_tool("good_tool", t, baseline_success=0.3, rollback="snap",
                     capability_widens=False, controller=_ctrl(tmp_path))
    assert v.ok


def test_propose_tool_rejected_when_it_widens_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    t = ToolOutcomeTracker(path=tmp_path / "to.json")
    for _ in range(6):
        t.record("greedy_tool", True)
    v = propose_tool("greedy_tool", t, baseline_success=0.3, rollback="snap",
                     capability_widens=True, controller=_ctrl(tmp_path))
    assert not v.ok


# -- Phase 1/2/4: verifier / policy / prompt -------------------------------

def test_propose_verifier_adopts_better_discriminator(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    v = propose_verifier("retrained head", baseline_discrimination=0.15,
                         candidate_discrimination=0.31, samples=12,
                         rollback="head-v1", controller=_ctrl(tmp_path))
    assert v.ok


def test_propose_policy_requires_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    v = propose_policy("rl adapter", baseline=0.5, candidate=0.51, samples=2,
                       rollback="adapter-v0", controller=_ctrl(tmp_path))
    assert not v.ok  # too few samples for the policy rung


# -- Phase 5: code self-mod through the validate seam ----------------------

def test_propose_code_blocked_by_failing_validate(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    v = propose_code("rewrite tool", validate=lambda: (False, "import failed in sandbox"),
                     eval_before=0.5, eval_after=0.9, samples=10, rollback="commit-abc",
                     approved=True, capability_widens=False, controller=_ctrl(tmp_path))
    assert not v.ok
    assert any(g.gate == "validate" for g in v.gates)


def test_propose_code_requires_human_even_when_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    common = dict(validate=lambda: (True, ""), eval_before=0.5, eval_after=0.9,
                  samples=10, rollback="commit-abc", capability_widens=False)
    assert not propose_code("rewrite", approved=False, controller=_ctrl(tmp_path), **common).ok
    assert propose_code("rewrite", approved=True, controller=_ctrl(tmp_path), **common).ok


# -- Phase 6: weights ------------------------------------------------------

def test_propose_weights_is_human_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    common = dict(eval_before=0.6, eval_after=0.75, samples=20, rollback="ckpt-1")
    assert not propose_weights("finetune", approved=False, controller=_ctrl(tmp_path), **common).ok
    assert propose_weights("finetune", approved=True, controller=_ctrl(tmp_path), **common).ok


def test_disabled_engine_blocks_all_producers(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_IMPROVEMENT", raising=False)
    from maverick.self_improvement import reset_shared
    reset_shared()
    v = propose_policy("x", baseline=0.1, candidate=0.9, samples=20, rollback="r")
    assert not v.ok
