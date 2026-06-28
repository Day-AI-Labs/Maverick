"""Tests for anchor-gated evaluator co-evolution (maverick.evaluator_evolution).

Deterministic and offline: no LLM, no network. We exercise the epsilon-best-belief
math, the anchor + its immutability governance, selective erasure, the
challenger-selection rule, and the end-to-end promotion routed through the
self-improvement governance spine.
"""
from __future__ import annotations

import pytest
from maverick import evaluator_evolution as ee
from maverick.self_improvement import SelfImprovementController

# -- epsilon-best-belief --------------------------------------------------------

def test_best_belief_no_evidence_is_eps_quantile_of_uniform():
    # Beta(1,1) is uniform; its 0.05-quantile is 0.05.
    assert ee.best_belief(0, 0, 0.05) == pytest.approx(0.05, abs=0.01)


def test_best_belief_in_unit_interval():
    for s, f in [(0, 0), (10, 0), (0, 10), (7, 3), (100, 1)]:
        bb = ee.best_belief(s, f)
        assert 0.0 <= bb <= 1.0


def test_best_belief_more_evidence_raises_lower_bound_at_same_ratio():
    # Same 8:2 ratio, ten times the evidence -> a tighter, higher lower bound.
    assert ee.best_belief(80, 20) > ee.best_belief(8, 2)


def test_best_belief_higher_success_ratio_scores_higher():
    assert ee.best_belief(10, 0) > ee.best_belief(5, 5)


def test_best_belief_is_below_the_posterior_mean():
    # The 0.05-quantile is a conservative under-estimate of the mean (9/12=0.75).
    assert ee.best_belief(8, 3, 0.05) < (1 + 8) / (2 + 8 + 3)


# -- Anchor + checksum ----------------------------------------------------------

def _anchor(role="reviewer", n=14, true_every=2):
    items = tuple(
        ee.AnchorItem(id=f"{role}-{i:04d}", label=(i % true_every == 0), prompt=f"p{i}")
        for i in range(n)
    )
    return ee.Anchor(role=role, items=items)


def test_checksum_ignores_prompt_but_tracks_labels():
    a = ee.Anchor("r", (ee.AnchorItem("x", True, "hello"),))
    same_label = ee.Anchor("r", (ee.AnchorItem("x", True, "WORLD"),))
    flipped = ee.Anchor("r", (ee.AnchorItem("x", False, "hello"),))
    assert a.checksum() == same_label.checksum()   # prompt text is not pinned
    assert a.checksum() != flipped.checksum()       # a flipped label is


def test_checksum_is_order_independent():
    a = ee.Anchor("r", (ee.AnchorItem("a", True), ee.AnchorItem("b", False)))
    b = ee.Anchor("r", (ee.AnchorItem("b", False), ee.AnchorItem("a", True)))
    assert a.checksum() == b.checksum()


def test_load_anchor_skips_malformed_rows(tmp_path):
    p = tmp_path / "reviewer.ndjson"
    p.write_text(
        '{"id": "a", "label": true, "prompt": "x"}\n'
        "not json\n"
        '{"missing label": 1}\n'
        '{"id": "b", "label": false}\n',
        encoding="utf-8",
    )
    a = ee.load_anchor(p, "reviewer")
    assert {it.id for it in a.items} == {"a", "b"}


def test_load_anchor_missing_file_is_empty():
    a = ee.load_anchor("/no/such/file.ndjson", "reviewer")
    assert len(a) == 0


# -- scoring by agreement -------------------------------------------------------

def test_score_on_anchor_counts_agreement_and_abstention():
    anchor = ee.Anchor("r", (
        ee.AnchorItem("a", True), ee.AnchorItem("b", False), ee.AnchorItem("c", True),
    ))
    # agrees on a and b, missing c -> abstention counts as a failure.
    s, f = ee.score_on_anchor({"a": True, "b": False}, anchor)
    assert (s, f) == (2, 1)


# -- selective erasure ----------------------------------------------------------

def test_selective_erasure_only_drops_displaced_records():
    recs = [
        ee.EvaluatorRecord("r1", "old"),
        ee.EvaluatorRecord("r2", "other"),
        ee.EvaluatorRecord("r3", "old"),
    ]
    kept, erased = ee.selective_erasure(recs, "old")
    assert [r.record_id for r in kept] == ["r2"]
    assert {r.record_id for r in erased} == {"r1", "r3"}


# -- challenger selection (ties favour the incumbent) ---------------------------

def test_choose_challenger_picks_strictly_better():
    wid, bb = ee.choose_challenger(0.5, [("c1", 0.4), ("c2", 0.7), ("c3", 0.6)])
    assert wid == "c2" and bb == pytest.approx(0.7)


def test_choose_challenger_tie_favours_incumbent():
    wid, bb = ee.choose_challenger(0.7, [("c1", 0.7), ("c2", 0.69)])
    assert wid is None and bb == pytest.approx(0.7)


# -- anchor governance (immutability lock) --------------------------------------

def test_lock_problems_clean_when_nothing_committed():
    assert ee.lock_problems(None, {}) == []


def test_lock_problems_flags_edited_released_anchor():
    a = _anchor()
    lock = ee.anchor_fingerprint({"reviewer": a})
    edited = ee.Anchor("reviewer", a.items[:-1] + (ee.AnchorItem("reviewer-0013", True),))
    problems = ee.lock_problems(lock, {"reviewer": edited})
    assert any("checksum changed" in p for p in problems)


def test_lock_problems_flags_new_and_removed_anchors():
    a = _anchor()
    lock = ee.anchor_fingerprint({"reviewer": a})
    # a brand-new role -> must regen.
    new = ee.lock_problems(lock, {"reviewer": a, "grader": _anchor("grader")})
    assert any("regen" in p.lower() or "new anchor" in p.lower() for p in new)
    # a released role gone -> hard fail.
    removed = ee.lock_problems(lock, {})
    assert any("gone from the anchor dir" in p for p in removed)


def test_verify_anchor_integrity_fails_open_without_lock_but_closed_on_mismatch():
    a = _anchor()
    assert ee.verify_anchor_integrity(a, lock=None) is True       # ungoverned -> open
    good = ee.anchor_fingerprint({"reviewer": a})
    assert ee.verify_anchor_integrity(a, lock=good) is True       # matches lock
    tampered = ee.Anchor("reviewer", a.items[:-1] + (ee.AnchorItem("reviewer-0013", True),))
    assert ee.verify_anchor_integrity(tampered, lock=good) is False  # mismatch -> closed


def test_committed_baseline_lock_is_valid_json():
    lock = ee.load_lock()
    assert isinstance(lock, dict) and "checksums" in lock


# -- end-to-end promotion through the governance spine --------------------------

def _ctrl(frozen=False, **kw):
    return SelfImprovementController(
        frozen_fn=lambda: frozen,
        audit_fn=lambda **k: None,
        **kw,
    )


def _verdicts(anchor, *, agree):
    """Build a verdict map that agrees on the first ``agree`` items (else flips)."""
    out = {}
    for i, it in enumerate(anchor.items):
        out[it.id] = it.label if i < agree else (not it.label)
    return out


def test_consider_promotion_no_op_when_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_IMPROVEMENT", raising=False)
    monkeypatch.delenv("MAVERICK_EVALUATOR_EVOLUTION", raising=False)
    anchor = _anchor()
    slot = ee.EvaluatorSlot(role="reviewer", evaluator_id="old")
    res = ee.consider_promotion(
        slot, _verdicts(anchor, agree=8),
        {"new": _verdicts(anchor, agree=14)}, anchor, [],
    )
    assert res.promoted is False
    assert slot.evaluator_id == "old" and slot.epoch == 1


def test_consider_promotion_promotes_better_judge_and_erases(monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    monkeypatch.setenv("MAVERICK_EVALUATOR_EVOLUTION", "1")
    monkeypatch.setattr(ee, "_audit", lambda *a, **k: None)
    anchor = _anchor(n=14)
    slot = ee.EvaluatorSlot(role="reviewer", evaluator_id="old")
    records = [ee.EvaluatorRecord("r1", "old"), ee.EvaluatorRecord("r2", "other")]
    # Controller that auto-promotes the evaluator rung (ceiling raised).
    ctrl = _ctrl(max_auto_rung="evaluator")
    res = ee.consider_promotion(
        slot,
        _verdicts(anchor, agree=8),               # incumbent: 8/14 agree
        {"new": _verdicts(anchor, agree=14)},     # challenger: 14/14 agree
        anchor, records, lock=None, controller=ctrl,
    )
    assert res.promoted is True
    assert res.challenger_id == "new"
    assert res.challenger_bb > res.incumbent_bb
    assert slot.evaluator_id == "new" and slot.epoch == 2
    # Only the displaced evaluator's records were erased.
    assert {r.record_id for r in res.erased} == {"r1"}
    assert {r.record_id for r in res.kept} == {"r2"}


def test_consider_promotion_blocked_by_calibration_freeze(monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    monkeypatch.setenv("MAVERICK_EVALUATOR_EVOLUTION", "1")
    monkeypatch.setattr(ee, "_audit", lambda *a, **k: None)
    anchor = _anchor(n=14)
    slot = ee.EvaluatorSlot(role="reviewer", evaluator_id="old")
    ctrl = _ctrl(frozen=True, max_auto_rung="evaluator")
    res = ee.consider_promotion(
        slot, _verdicts(anchor, agree=8), {"new": _verdicts(anchor, agree=14)},
        anchor, [], lock=None, controller=ctrl,
    )
    assert res.promoted is False
    assert "frozen" in res.reason or "calibration" in res.reason.lower()
    assert slot.evaluator_id == "old" and slot.epoch == 1


def test_consider_promotion_needs_human_above_default_ceiling(monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    monkeypatch.setenv("MAVERICK_EVALUATOR_EVOLUTION", "1")
    monkeypatch.setattr(ee, "_audit", lambda *a, **k: None)
    anchor = _anchor(n=14)
    slot = ee.EvaluatorSlot(role="reviewer", evaluator_id="old")
    # Default ceiling is "policy", below "evaluator": a swap needs approval.
    ctrl = _ctrl()  # max_auto_rung defaults to "policy"
    refused = ee.consider_promotion(
        slot, _verdicts(anchor, agree=8), {"new": _verdicts(anchor, agree=14)},
        anchor, [], lock=None, controller=ctrl,
    )
    assert refused.promoted is False
    # With explicit human approval the same swap goes through.
    approved = ee.consider_promotion(
        slot, _verdicts(anchor, agree=8), {"new": _verdicts(anchor, agree=14)},
        anchor, [], lock=None, controller=ctrl, approved=True,
    )
    assert approved.promoted is True


def test_consider_promotion_refuses_tampered_anchor(monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    monkeypatch.setenv("MAVERICK_EVALUATOR_EVOLUTION", "1")
    monkeypatch.setattr(ee, "_audit", lambda *a, **k: None)
    anchor = _anchor(n=14)
    # Lock pins a DIFFERENT anchor; the live one won't match -> refuse.
    other = _anchor(n=14, true_every=3)
    lock = ee.anchor_fingerprint({"reviewer": other})
    slot = ee.EvaluatorSlot(role="reviewer", evaluator_id="old")
    res = ee.consider_promotion(
        slot, _verdicts(anchor, agree=8), {"new": _verdicts(anchor, agree=14)},
        anchor, [], lock=lock, controller=_ctrl(max_auto_rung="evaluator"),
    )
    assert res.promoted is False
    assert "integrity" in res.reason
