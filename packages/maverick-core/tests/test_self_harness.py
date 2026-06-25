"""Self-Harness: governed, model-specific harness-addendum learning loop.

Covers the four stages (mine -> propose -> validate -> gate) plus the safety
properties: OFF by default, model isolation, the held-in/held-out acceptance
rule (no pure trades), gate-refusal leaves the store untouched, and a promoted
addendum is recalled into the prompt.
"""
from __future__ import annotations

import json

import pytest
from maverick import self_harness as sh
from maverick import self_improvement as si


def _refl(model_id, fclass, goal, msg="boom"):
    return {"model_id": model_id, "failure_class": fclass,
            "goal_text": goal, "failure_msg": msg}


@pytest.fixture
def store(tmp_path):
    return tmp_path / "addenda.json"


# ---------- off by default ----------

def test_disabled_by_default(monkeypatch, store):
    monkeypatch.delenv("MAVERICK_SELF_HARNESS", raising=False)
    monkeypatch.setattr("maverick.config.load_config", dict)
    assert sh.enabled() is False
    assert sh.recall_addendum("m", store) == ""           # disabled -> no prompt change
    rep = sh.run_self_harness([], model_id="m", path=store)
    assert rep.skipped == ["disabled"] and rep.promoted == 0


# ---------- MINE ----------

def test_mine_is_model_specific_and_needs_support(monkeypatch):
    refl = [
        _refl("A", "timeout", "export the nightly ledger report"),
        _refl("A", "timeout", "export the ledger report again"),
        _refl("A", "timeout", "export ledger report nightly run"),
        _refl("B", "timeout", "export the nightly ledger report"),   # other model
        _refl("A", "auth", "log into the partner portal"),           # below support
    ]
    sigs = sh.mine_failures(refl, model_id="A", min_support=3)
    assert len(sigs) == 1                      # only the model-A timeout cluster
    assert sigs[0].model_id == "A" and sigs[0].failure_class == "timeout"
    assert sigs[0].support == 3
    # Model B's identical failure does NOT contribute to A's signatures.
    assert sh.mine_failures(refl, model_id="B", min_support=3) == []
    # min_support < 1 disables mining entirely.
    assert sh.mine_failures(refl, model_id="A", min_support=0) == []


# ---------- PROPOSE ----------

def test_propose_uses_seam_and_rejects_oversized(monkeypatch):
    sig = sh.FailureSignature("A", "timeout", "timeout: timed out", 3, ("g",))
    # Injected proposer is preferred over the deterministic fallback.
    p = sh.propose_addendum(sig, propose_fn=lambda s: "Verify the export window first.")
    assert p and p.addendum_line == "Verify the export window first."
    # An over-long 'minimal' edit is refused.
    assert sh.propose_addendum(sig, propose_fn=lambda s: "x" * 400) is None
    # A proposer that raises can't crash the loop.
    assert sh.propose_addendum(sig, propose_fn=lambda s: 1 / 0) is None


# ---------- VALIDATE ----------

def _sig_proposal():
    sig = sh.FailureSignature("A", "timeout", "timeout: timed out", 3, ("g",))
    return sh.propose_addendum(sig, propose_fn=lambda s: "Verify the window first.")


def test_validate_accepts_only_non_regressing_improvement():
    p = _sig_proposal()
    helps = sh.validate_proposal(
        p, held_in=["a", "b"], held_out=["c", "d", "e"],
        score_with=lambda a, c: 0.9, score_without=lambda a, c: 0.5)
    assert helps.accepted and helps.samples == 5
    assert helps.baseline_score == 0.5 and helps.candidate_score == 0.9


def test_validate_rejects_pure_trade_and_no_op():
    p = _sig_proposal()
    # Helps held-in but REGRESSES held-out -> reject (the overfitting failure).
    trade = sh.validate_proposal(
        p, held_in=["a"], held_out=["c"],
        score_with=lambda a, c: 0.9 if c == ["a"] else 0.2,
        score_without=lambda a, c: 0.5)
    assert not trade.accepted and "regressed" in trade.reason
    # Helps neither split -> reject.
    noop = sh.validate_proposal(
        p, held_in=["a"], held_out=["c"],
        score_with=lambda a, c: 0.5, score_without=lambda a, c: 0.5)
    assert not noop.accepted and "no improvement" in noop.reason


# ---------- store + recall ----------

def test_store_roundtrip_and_recall(monkeypatch, store):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    p = _sig_proposal()
    sh._apply_addendum(p, path=store)
    text = sh.recall_addendum("A", store)
    assert "Verify the window first." in text
    assert "Operating guidance" in text
    assert sh.recall_addendum("B", store) == ""           # other model untouched
    # Rollback handle restores the prior (empty) state.
    rb = sh._rollback_handle(store)
    sh._apply_addendum(_sig_proposal(), path=store)        # second write
    rb()                                                   # undo back to one line
    assert json.loads(store.read_text())["A"].count("Verify the window first.") == 1


# ---------- GATE (full promote + refusal) ----------

def _enable(monkeypatch, frozen=False):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    monkeypatch.setattr(si, "enabled", lambda: True)
    return si.SelfImprovementController(frozen_fn=lambda: frozen,
                                        ledger=si.PromotionLedger())


def test_full_loop_promotes_through_the_gate(monkeypatch, store):
    ctrl = _enable(monkeypatch)
    refl = [
        _refl("A", "timeout", "export the nightly ledger report"),
        _refl("A", "timeout", "export the ledger report again"),
        _refl("A", "timeout", "export ledger report nightly run"),
    ]
    rep = sh.run_self_harness(
        refl, model_id="A", controller=ctrl, min_support=3, path=store,
        held_in=["a", "b"], held_out=["c", "d", "e", "f", "g"],
        score_with=lambda a, c: 0.9, score_without=lambda a, c: 0.4)
    assert rep.mined == 1 and rep.validated == 1 and rep.promoted == 1
    # The learned line is now recalled into A's prompt.
    assert "timeout" in sh.recall_addendum("A", store).lower()


def test_gate_refusal_leaves_store_untouched(monkeypatch, store):
    # Verifier frozen (calibration drift) -> the gate refuses; nothing is written.
    ctrl = _enable(monkeypatch, frozen=True)
    refl = [
        _refl("A", "timeout", "export the nightly ledger report"),
        _refl("A", "timeout", "export the ledger report again"),
        _refl("A", "timeout", "export ledger report nightly run"),
    ]
    rep = sh.run_self_harness(
        refl, model_id="A", controller=ctrl, min_support=3, path=store,
        held_in=["a", "b"], held_out=["c", "d", "e", "f", "g"],
        score_with=lambda a, c: 0.9, score_without=lambda a, c: 0.4)
    assert rep.validated == 1 and rep.promoted == 0
    assert any("gate refused" in s for s in rep.skipped)
    assert not store.exists()                              # store never written
    assert sh.recall_addendum("A", store) == ""


def test_dry_run_without_scorer_applies_nothing(monkeypatch, store):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    refl = [
        _refl("A", "timeout", "export the nightly ledger report"),
        _refl("A", "timeout", "export the ledger report again"),
        _refl("A", "timeout", "export ledger report nightly run"),
    ]
    rep = sh.run_self_harness(refl, model_id="A", min_support=3, path=store)
    assert rep.mined == 1 and rep.proposed == 1 and rep.promoted == 0
    assert any("dry" in s for s in rep.skipped)
    assert not store.exists()


# ---------- CLI inspector ----------

def test_cli_requires_enable(monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main
    monkeypatch.delenv("MAVERICK_SELF_HARNESS", raising=False)
    monkeypatch.setattr("maverick.config.load_config", dict)
    res = CliRunner().invoke(main, ["self-harness", "--model", "m"])
    assert res.exit_code != 0 and "self-harness is off" in res.output


def test_cli_reports_mined_weaknesses(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from maverick import reflexion
    from maverick.cli import main
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    p = tmp_path / "r.ndjson"
    for goal in ("export the nightly ledger", "export the ledger again",
                 "export ledger nightly run"):
        reflexion.record(goal, "timeout", "timed out", "r", model_id="m", path=p)
    monkeypatch.setattr(reflexion, "default_path", lambda: p)
    res = CliRunner().invoke(main, ["self-harness", "--model", "m", "--min-support", "3"])
    assert res.exit_code == 0
    assert "Weaknesses for 'm'" in res.output and "would add:" in res.output
