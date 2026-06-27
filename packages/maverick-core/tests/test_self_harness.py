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


def test_count_eligible_matches_mining_filter():
    # count_eligible must agree with mine_failures' guard: model-tagged AND
    # unscoped only. Scoped, other-model, and malformed records don't count.
    recs = (
        [{"model_id": "m", "failure_class": "t", "goal_text": f"g{i}",
          "channel": None, "user_id": None} for i in range(3)]
        + [{"model_id": "m", "failure_class": "t", "goal_text": "s",
            "channel": "slack:x", "user_id": "u"}]      # scoped -> excluded
        + [{"model_id": "other", "failure_class": "t", "goal_text": "o"}]  # other model
        + [None, {"no": "model"}]                        # malformed
    )
    assert sh.count_eligible(recs, model_id="m") == 3
    assert sh.count_eligible([], model_id="m") == 0
    # Exactly the records mine_failures would consider (min_support=1).
    assert len(sh.mine_failures(recs, model_id="m", min_support=1)) >= 1


# ---------- CLI inspector ----------

def test_cli_requires_enable(monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main
    monkeypatch.delenv("MAVERICK_SELF_HARNESS", raising=False)
    monkeypatch.setattr("maverick.config.load_config", dict)
    res = CliRunner().invoke(main, ["self-harness", "preview", "--model", "m"])
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
    res = CliRunner().invoke(main, ["self-harness", "preview", "--model", "m", "--min-support", "3"])
    assert res.exit_code == 0
    assert "Weaknesses for 'm'" in res.output and "would add:" in res.output


# ---------- gate reason surfaced + runner wiring ----------

def _three(model="M", fclass="timeout"):
    return [{"model_id": model, "failure_class": fclass,
             "goal_text": f"export the ledger run {i}", "failure_msg": "t"}
            for i in range(3)]


def test_pass_caps_promotions_and_keeps_strongest(monkeypatch, store):
    # A single pass must promote at most _MAX_LINES_PER_MODEL lines and never
    # audit a line it would immediately evict under the newest-wins cap. Found
    # by the 100k soak: with >8 distinct signatures, the cap was silently
    # dropping the STRONGEST (highest-support, processed first) guidance.
    ctrl = _enable(monkeypatch)
    # 12 distinct failure classes for one model, each a 3-failure cluster, with
    # decreasing support so the ordering (strongest first) is unambiguous.
    recs = []
    for k in range(12):
        n = 14 - k                       # support 14, 13, ... -> strictly decreasing
        recs += [{"model_id": "M", "failure_class": f"cls{k}",
                  "goal_text": f"task alpha run {i}", "failure_msg": f"err{k}"}
                 for i in range(n)]
    rep = sh.run_self_harness(
        recs, model_id="M", min_support=3, controller=ctrl, path=store,
        held_in=["a", "b"], held_out=["c", "d", "e"],
        score_with=lambda a, c: 0.95, score_without=lambda a, c: 0.4)
    assert rep.promoted == sh._MAX_LINES_PER_MODEL          # capped, not 12
    recalled = sh.recall_addendum("M", store)
    # Every promoted line is actually live (no phantom promotion).
    assert all(line in recalled for line in rep.applied_lines)
    # The strongest weaknesses (cls0/cls1, highest support) were kept.
    assert "cls0" in recalled and "cls1" in recalled
    assert any("at capacity" in s for s in rep.skipped)


def test_gate_reason_is_surfaced(monkeypatch, store):
    # Too few validation samples for the prompt rung (min 5): the refusal must
    # say WHY, not just "gate refused" (found by the 50-round stress campaign).
    ctrl = _enable(monkeypatch)
    rep = sh.run_self_harness(
        _three(), model_id="M", min_support=3, controller=ctrl, path=store,
        held_in=["a"], held_out=["b"],
        score_with=lambda a, c: 0.9, score_without=lambda a, c: 0.4)
    assert rep.promoted == 0
    assert any("insufficient evidence" in s and "5 samples" in s for s in rep.skipped)
    assert not store.exists()


def test_runner_pass_disabled(monkeypatch):
    from maverick import self_improvement_runner as runner
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "0")
    monkeypatch.setattr("maverick.config.load_config", dict)
    rep = runner.run_self_harness_pass(_three(), model_id="M")
    assert rep.promoted == 0 and rep.mined == 0      # no-op, never raises


def test_runner_pass_driven_delegates_to_loop(monkeypatch):
    from maverick import self_improvement_runner as runner
    ctrl = _enable(monkeypatch)                       # sets SELF_HARNESS=1 + SI on
    rep = runner.run_self_harness_pass(
        _three(), model_id="M", controller=ctrl,
        score_with=lambda a, c: 0.95, score_without=lambda a, c: 0.4)
    # The runner loads/forwards to the real loop: the weakness is mined and a
    # line proposed (promotion depends on sample count, exercised elsewhere).
    assert rep.mined == 1 and rep.proposed == 1


# ---------- 50-round stress campaign (CI regression guard) ----------

def test_stress_50_rounds_invariants(monkeypatch, tmp_path):
    """Run the real mine->propose->validate->gate loop across 50 seeded,
    adversarial rounds + a 20-step accumulation stress, asserting the safety
    invariants every round. Deterministic (seeded), so it's a guard, not a
    flake."""
    import random as _random

    models = ["A", "B", "C"]
    stems = ["export the ledger", "reconcile invoices", "audit the logs",
             "deploy billing", "migrate db"]
    classes = ["timeout", "auth", "tool_error", "shield"]
    shared = tmp_path / "shared.json"
    viol: list[str] = []

    def ck(rd, cond, msg):
        if not cond:
            viol.append(f"[r{rd}] {msg}")

    for n in range(1, 51):
        rng = _random.Random(n)
        ms = rng.sample(models, rng.randint(1, 3))
        target = rng.choice(ms)
        recs = []
        for _ in range(rng.randint(1, 3)):
            m, fc, st = rng.choice(ms), rng.choice(classes), rng.choice(stems)
            recs += [{"model_id": m, "failure_class": fc,
                      "goal_text": f"{st} run {i}", "failure_msg": fc}
                     for i in range(rng.randint(2, 5))]
        sh_on, si_on = rng.random() < 0.9, rng.random() < 0.8
        frozen, dry = rng.random() < 0.2, rng.random() < 0.15
        reuse = rng.random() < 0.5
        path = shared if reuse else (tmp_path / f"s{n}.json")
        monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1" if sh_on else "0")
        monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1" if si_on else "0")
        ctrl = si.SelfImprovementController(frozen_fn=lambda f=frozen: f,
                                            ledger=si.PromotionLedger())
        sw = (lambda a, c: 0.9) if not dry else None
        wo = (lambda a, c: 0.4) if not dry else None
        held_in = [f"{rng.choice(stems)} run {i}" for i in range(rng.randint(2, 3))]
        held_out = [f"{rng.choice(stems)} unseen {i}" for i in range(rng.randint(3, 5))]

        before = sh.load_addenda(path)
        others = {m: (sh.recall_addendum(m, path) if sh_on else "")
                  for m in models if m != target}
        try:
            rep = sh.run_self_harness(
                recs, model_id=target, min_support=rng.randint(1, 4),
                held_in=held_in, held_out=held_out, score_with=sw, score_without=wo,
                controller=ctrl, path=path)
        except Exception as e:
            ck(n, False, f"RAISED {type(e).__name__}: {e}")
            continue
        after = sh.load_addenda(path)
        ck(n, rep.promoted == len(rep.applied_lines), "promoted != applied_lines")
        if not sh_on:
            ck(n, rep.promoted == 0 and after == before, "disabled not a no-op")
            continue
        if rep.promoted > 0:
            ck(n, si_on and not frozen and not dry, "promoted under a closed gate")
            recalled = sh.recall_addendum(target, path)
            ck(n, all(ln in recalled for ln in rep.applied_lines), "line not recalled")
            ck(n, len(recalled) <= sh._MAX_ADDENDUM_CHARS, "addendum over char bound")
        if rep.promoted == 0:
            ck(n, after.get(target, "") == before.get(target, ""), "no-promote changed store")
        for m, prev in others.items():
            ck(n, sh.recall_addendum(m, path) == prev, f"model isolation broke for {m}")

    # accumulation to the cap
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    ctrl = si.SelfImprovementController(frozen_fn=lambda: False, ledger=si.PromotionLedger())
    acc = tmp_path / "acc.json"
    for k in range(20):
        recs = [{"model_id": "M", "failure_class": f"c{k}",
                 "goal_text": f"task run {i}", "failure_msg": f"err{k}"} for i in range(3)]
        rep = sh.run_self_harness(
            recs, model_id="M", min_support=3,
            held_in=["task run 0", "task run 1"],
            held_out=["u0", "u1", "u2", "u3"],
            score_with=lambda a, c: 0.95, score_without=lambda a, c: 0.4,
            controller=ctrl, path=acc)
        ck(100 + k, rep.promoted == 1, f"acc expected promote, got {rep.skipped}")
        lines = [ln for ln in sh.recall_addendum("M", acc).splitlines()
                 if ln.strip().startswith("- ")]
        ck(100 + k, len(lines) <= sh._MAX_LINES_PER_MODEL, "over line cap")
        ck(100 + k, len(lines) == len(set(lines)), "duplicate line in block")
    final = [ln for ln in sh.recall_addendum("M", acc).splitlines()
             if ln.strip().startswith("- ")]
    ck(200, len(final) == sh._MAX_LINES_PER_MODEL, f"cap not reached: {len(final)}")

    assert not viol, "invariant violations:\n" + "\n".join(viol)
