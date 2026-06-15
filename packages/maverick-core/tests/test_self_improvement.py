"""Tests for the governed self-improvement controller.

Deterministic and offline: no LLM, no torch, no training. We exercise the
governance spine -- the gate pipeline, the capability-non-escalation proof, the
calibration freeze, human approval, reversibility, audit, and the ledger.
"""
from __future__ import annotations

from maverick.self_improvement import (
    Candidate,
    PromotionLedger,
    SelfImprovementController,
    consider,
    reset_shared,
)


class _Grant:
    """Minimal capability stand-in: permits a fixed set of tools."""

    def __init__(self, tools):
        self._tools = set(tools)

    def permits(self, tool, *, now=None):
        return tool in self._tools


def _ctrl(audit=None, frozen=False, **kw):
    return SelfImprovementController(
        frozen_fn=lambda: frozen,
        audit_fn=(audit if audit is not None else (lambda **k: None)),
        **kw,
    )


def _cand(**kw):
    base = dict(
        rung="config", summary="tweak", baseline_score=0.5, candidate_score=0.7,
        samples=5, rollback="snap-1",
    )
    base.update(kw)
    return Candidate(**base)


# -- evaluate(): gate logic (pure, no env / no enable needed) --------------

def test_promotes_config_rung_when_it_beats_baseline():
    v = _ctrl().evaluate(_cand(rung="config", baseline_score=0.5, candidate_score=0.7))
    assert v.ok
    assert all(g.ok for g in v.gates)


def test_no_improvement_is_rejected():
    v = _ctrl().evaluate(_cand(candidate_score=0.5))  # == baseline
    assert not v.ok
    assert any(g.gate == "evidence" and not g.ok for g in v.gates)


def test_insufficient_samples_is_rejected():
    v = _ctrl().evaluate(_cand(rung="config", samples=1))
    assert not v.ok
    assert "evidence" in v.blocking_reason or "sample" in v.blocking_reason.lower()


def test_calibration_freeze_blocks_all_promotion():
    v = _ctrl(frozen=True).evaluate(_cand())
    assert not v.ok
    assert any(g.gate == "calibration" and not g.ok for g in v.gates)


def test_frozen_fn_error_fails_closed():
    def boom():
        raise RuntimeError("cannot reach calibration verdict")

    ctrl = SelfImprovementController(frozen_fn=boom, audit_fn=lambda **k: None)
    v = ctrl.evaluate(_cand())
    assert not v.ok  # can't confirm the judge is honest -> refuse


# -- capability non-escalation (the core safety property) ------------------

def test_tool_rung_without_capability_proof_is_rejected():
    v = _ctrl().evaluate(_cand(rung="tool", samples=5))
    assert not v.ok
    assert any(g.gate == "capability" and not g.ok for g in v.gates)


def test_tool_rung_with_non_escalation_proof_promotes():
    v = _ctrl().evaluate(_cand(rung="tool", samples=5, capability_widens=False))
    assert v.ok


def test_declared_widening_is_rejected():
    v = _ctrl().evaluate(_cand(rung="tool", samples=5, capability_widens=True))
    assert not v.ok
    assert any(g.gate == "capability" and not g.ok for g in v.gates)


def test_capability_probe_detects_widening_from_grants():
    before, after = _Grant({"read_file"}), _Grant({"read_file", "shell"})
    v = _ctrl().evaluate(_cand(
        rung="tool", samples=5,
        capability_before=before, capability_after=after,
        probe_tools=("read_file", "shell"),
    ))
    assert not v.ok  # 'shell' is newly permitted -> escalation


def test_capability_probe_passes_when_bounded():
    before, after = _Grant({"read_file", "shell"}), _Grant({"read_file"})
    v = _ctrl().evaluate(_cand(
        rung="tool", samples=5,
        capability_before=before, capability_after=after,
        probe_tools=("read_file", "shell"),
    ))
    assert v.ok  # strictly narrower -> bounded


# -- human approval & the auto-promotion ceiling ---------------------------

def test_code_rung_requires_human_approval():
    v = _ctrl().evaluate(_cand(rung="code", samples=10, capability_widens=False, approved=False))
    assert not v.ok
    assert any(g.gate == "human_approval" and not g.ok for g in v.gates)
    v2 = _ctrl().evaluate(_cand(rung="code", samples=10, capability_widens=False, approved=True))
    assert v2.ok


def test_max_auto_rung_ceiling_forces_human_above_it():
    # Ceiling at 'config' means even a 'policy' change needs a human.
    ctrl = _ctrl(max_auto_rung="config")
    v = ctrl.evaluate(_cand(rung="policy", samples=8, capability_widens=False, approved=False))
    assert not v.ok
    assert any(g.gate == "human_approval" and not g.ok for g in v.gates)


# -- reversibility ---------------------------------------------------------

def test_non_reversible_change_is_rejected():
    v = _ctrl().evaluate(_cand(rollback=None))
    assert not v.ok
    assert any(g.gate == "rollback" and not g.ok for g in v.gates)


def test_unknown_rung_is_rejected():
    v = _ctrl().evaluate(_cand(rung="weights_and_biases"))
    assert not v.ok


# -- promote()/rollback() with a ledger + audit ----------------------------

def test_promote_records_and_audits(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    audited = []
    ledger = PromotionLedger(path=tmp_path / "si.json")
    ctrl = _ctrl(audit=lambda **k: audited.append(k), ledger=ledger)
    cand = _cand(rung="config")
    v = ctrl.promote(cand)
    assert v.ok
    assert ledger.get(cand.id) is not None
    assert any(a.get("decision") == "promote" for a in audited)


def test_rejected_promotion_is_audited_but_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    audited = []
    ledger = PromotionLedger(path=tmp_path / "si.json")
    ctrl = _ctrl(audit=lambda **k: audited.append(k), ledger=ledger)
    cand = _cand(candidate_score=0.4)  # below baseline
    v = ctrl.promote(cand)
    assert not v.ok
    assert ledger.get(cand.id) is None
    assert any(a.get("decision") == "reject" for a in audited)


def test_rollback_reverses_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    audited = []
    ledger = PromotionLedger(path=tmp_path / "si.json")
    ctrl = _ctrl(audit=lambda **k: audited.append(k), ledger=ledger)
    cand = _cand(rung="config")
    ctrl.promote(cand)
    undone = []
    assert ctrl.rollback(cand.id, undo=lambda: undone.append(True)) is True
    assert undone == [True]
    assert ledger.get(cand.id).rolled_back is True
    assert any(a.get("decision") == "rollback" for a in audited)
    # Second rollback is a no-op.
    assert ctrl.rollback(cand.id, undo=lambda: undone.append(True)) is False


def test_ledger_persists_across_instances(tmp_path):
    p = tmp_path / "si.json"
    from maverick.self_improvement import PromotionRecord
    led = PromotionLedger(path=p)
    led.add(PromotionRecord(id="abc", rung="config", summary="x",
                            baseline_score=0.1, candidate_score=0.9, promoted_at=1.0))
    reloaded = PromotionLedger(path=p)
    assert reloaded.get("abc") is not None
    assert reloaded.get("abc").candidate_score == 0.9


# -- disabled-by-default posture (kernel rule 1) ---------------------------

def test_disabled_by_default_is_a_noop(monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_IMPROVEMENT", raising=False)
    reset_shared()
    v = consider(_cand(rung="config"))
    assert not v.ok
    assert "disabled" in v.blocking_reason


def test_consider_promotes_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    ledger = PromotionLedger(path=tmp_path / "si.json")
    ctrl = _ctrl(ledger=ledger)
    v = consider(_cand(rung="config"), controller=ctrl)
    assert v.ok
