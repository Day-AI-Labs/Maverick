"""Tests for the self-improving factory (maverick.factory_learning).

Recording/mining/promotion all route through tmp ledgers and a fake gate, so
nothing touches the real ~/.maverick state or the live controller. The whole
loop is gated off by default; we flip MAVERICK_FACTORY_LEARNING per test.
"""
from __future__ import annotations

import pytest
from maverick import factory_learning as fl
from maverick.factory_learning import (
    SIGNAL_SKILL_GAP,
    SIGNAL_TOOL_MISSING,
    ProposerCorrection,
)


@pytest.fixture
def on(monkeypatch, tmp_path):
    """Enable the loop and point its ledgers at tmp files."""
    monkeypatch.setenv("MAVERICK_FACTORY_LEARNING", "1")
    out = tmp_path / "outcomes.ndjson"
    promoted = tmp_path / "promoted.ndjson"
    monkeypatch.setattr(fl, "OUTCOMES_PATH", out)
    monkeypatch.setattr(fl, "PROMOTED_PATH", promoted)
    return out, promoted


# --------------------------------------------------------------------------
# gating
# --------------------------------------------------------------------------
def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_FACTORY_LEARNING", raising=False)
    monkeypatch.setattr("maverick.self_improvement.enabled", lambda: False)
    assert fl.enabled() is False
    # Recording is a no-op while off.
    assert fl.record_outcome("finance_x", SIGNAL_TOOL_MISSING, detail="web_search") is False
    assert fl.augment_system_prompt("BASE") == "BASE"


def test_record_rejects_unknown_signal(on):
    assert fl.record_outcome("p", "not_a_signal", detail="x") is False


# --------------------------------------------------------------------------
# recording + mining
# --------------------------------------------------------------------------
def test_record_and_load_roundtrip(on):
    out, _ = on
    assert fl.record_outcome("finance_close", SIGNAL_TOOL_MISSING, detail="web_search")
    loaded = fl.load_outcomes(path=out)
    assert len(loaded) == 1
    assert loaded[0].pack == "finance_close" and loaded[0].detail == "web_search"
    # suite is inferred from the pack name prefix.
    assert loaded[0].suite == "finance"


def test_mine_requires_min_support(on):
    # Three DISTINCT packs hit the same gap -> one correction.
    for pack in ("finance_a", "finance_b", "finance_c"):
        fl.record_outcome(pack, SIGNAL_TOOL_MISSING, detail="web_search")
    # A fourth record from an already-counted pack must NOT inflate support.
    fl.record_outcome("finance_a", SIGNAL_TOOL_MISSING, detail="web_search")

    assert fl.mine_corrections(min_support=4) == []
    corr = fl.mine_corrections(min_support=3)
    assert len(corr) == 1
    assert corr[0].support == 3            # distinct packs, not 4 records
    assert corr[0].scope == "finance"
    assert "web_search" in corr[0].guidance


def test_mine_groups_by_scope_and_detail(on):
    fl.record_outcome("finance_a", SIGNAL_TOOL_MISSING, detail="web_search")
    fl.record_outcome("finance_b", SIGNAL_TOOL_MISSING, detail="web_search")
    fl.record_outcome("hr_a", SIGNAL_SKILL_GAP, detail="onboarding-checklist")
    corr = fl.mine_corrections(min_support=2)
    assert len(corr) == 1 and corr[0].detail == "web_search"


def test_record_provisioning_attributes_gaps(on):
    class _Profile:
        name = "finance_recon"

    def _gap(need):
        g = type("G", (), {})()
        g.resolution, g.need = "generate_tool", need
        return g

    class _Plan:
        # a DECLARED tool appears once even if duplicated; the sanitized
        # post-synthesis name (result.generated) is NOT recorded separately.
        tool_gaps = [_gap("ledger_fetch"), _gap("ledger_fetch")]

    class _Result:
        generated = ["ledger_fetch_sanitized"]
        acquired = ["three-way-match"]

    n = fl.record_provisioning(_Profile(), _Plan(), _Result())
    assert n == 2  # one tool-missing (deduped) + one skill-gap; no double/fragment
    details = {o.detail for o in fl.load_outcomes(path=on[0])}
    assert details == {"ledger_fetch", "three-way-match"}


# --------------------------------------------------------------------------
# promotion through the gate
# --------------------------------------------------------------------------
class _FakeVerdict:
    def __init__(self, promote):
        self.promote = promote


class _AcceptController:
    def evaluate(self, cand):
        # Sanity: a factory correction must never claim to widen authority.
        assert cand.capability_widens is False
        assert cand.rung == "prompt"
        return _FakeVerdict(True)


class _RejectController:
    def evaluate(self, cand):
        return _FakeVerdict(False)


def test_review_and_promote_persists_accepted(on):
    for pack in ("finance_a", "finance_b", "finance_c"):
        fl.record_outcome(pack, SIGNAL_TOOL_MISSING, detail="web_search")
    promoted = fl.review_and_promote(min_support=3, controller=_AcceptController())
    assert len(promoted) == 1
    # Persisted -> promoted_corrections sees it, and a re-run won't double-promote.
    assert len(fl.promoted_corrections(path=on[1])) == 1
    assert fl.review_and_promote(min_support=3, controller=_AcceptController()) == []


def test_review_and_promote_respects_rejection(on):
    for pack in ("finance_a", "finance_b", "finance_c"):
        fl.record_outcome(pack, SIGNAL_TOOL_MISSING, detail="web_search")
    assert fl.review_and_promote(min_support=3, controller=_RejectController()) == []
    assert fl.promoted_corrections(path=on[1]) == []


def test_default_scorer_scales_with_prevalence():
    corr = ProposerCorrection(scope="finance", signal=SIGNAL_TOOL_MISSING,
                              detail="web_search", support=3, guidance="g")
    base, cand, samples = fl._default_scorer(corr, total_packs=6)
    assert samples == 3
    assert cand == 1.0
    assert base == pytest.approx(0.5)   # 1 - 3/6
    assert cand - base > 0              # a real improvement the gate can weigh


# --------------------------------------------------------------------------
# application: scope-matched guidance in the system prompt
# --------------------------------------------------------------------------
def test_guidance_block_is_scope_matched(on, monkeypatch):
    monkeypatch.setattr(fl, "promoted_corrections", lambda **_: [
        ProposerCorrection("finance", SIGNAL_TOOL_MISSING, "web_search", 4, "use web_search"),
        ProposerCorrection("*", SIGNAL_SKILL_GAP, "kyc", 5, "know kyc"),
        ProposerCorrection("hr", SIGNAL_TOOL_MISSING, "ats", 3, "use ats"),
    ])
    fin = fl.guidance_block("finance")
    assert "use web_search" in fin and "know kyc" in fin   # finance + global
    assert "use ats" not in fin                            # not another suite's

    base = fl.augment_system_prompt("BASE", suite="finance")
    assert base.startswith("BASE\n") and "use web_search" in base


def test_guidance_block_empty_when_nothing_promoted(on):
    assert fl.guidance_block("finance") == ""
    assert fl.augment_system_prompt("BASE", suite="finance") == "BASE"


def test_loaders_survive_nondict_json_lines(on):
    # A corrupt/tampered ledger line that is valid JSON but NOT an object
    # (a bare int / string / array / bool / null) must be skipped, not crash the
    # loader -- mining/promotion/guidance all read these on the generation path.
    out, promoted = on
    out.write_text(
        '123\n"str"\n[1,2]\ntrue\nnull\nNOPE\n'
        '{"pack":"finance_a","signal":"tool_declared_but_missing","detail":"web_search",'
        '"ts":1,"suite":"finance"}\n'
    )
    rows = fl.load_outcomes(path=out)
    assert len(rows) == 1 and rows[0].pack == "finance_a"

    promoted.write_text(
        '42\n[]\n"x"\n{"scope":"finance","signal":"tool_declared_but_missing",'
        '"detail":"x","support":3,"guidance":"g"}\n'
    )
    assert len(fl.promoted_corrections(path=promoted)) == 1


def test_outcomes_ledger_is_bounded(on, monkeypatch):
    # The ledger must not grow without limit -- oldest rows roll off past the cap
    # (matching trajectory_store), keeping mining/promotion's whole-file re-read cheap.
    out, _ = on
    monkeypatch.setattr(fl, "_MAX_OUTCOME_ROWS", 200)
    monkeypatch.setattr(fl, "_ROTATE_BYTES", 200 * 60)  # small byte budget to trigger trim
    for i in range(2000):
        fl.record_outcome(f"pack_{i}", SIGNAL_TOOL_MISSING, detail="x", path=out)
    rows = fl.load_outcomes(path=out)
    assert len(rows) <= 400                       # bounded near the cap
    assert rows[-1].pack == "pack_1999"           # newest kept
    assert all(r.pack != "pack_0" for r in rows)  # oldest rolled off


def test_rotation_triggers_across_processes(on, monkeypatch):
    # Regression for the counter bug: rotation must fire on FILE SIZE, not a
    # process-local counter -- otherwise a fresh CLI process (a few rows each)
    # never trips it and the cap is a no-op. Simulate by resetting any process
    # state between batches; a size-based trigger still bounds the file.
    out, _ = on
    monkeypatch.setattr(fl, "_MAX_OUTCOME_ROWS", 100)
    monkeypatch.setattr(fl, "_ROTATE_BYTES", 100 * 60)
    for batch in range(50):          # 50 "processes" x 5 rows = 250, cap 100
        for i in range(5):
            fl.record_outcome(f"p{batch}_{i}", SIGNAL_TOOL_MISSING, detail="x", path=out)
    assert len(fl.load_outcomes(path=out)) <= 200   # bounded regardless of batch count


def test_persist_promoted_is_fail_soft(on, tmp_path):
    # Writing to a path whose parent is a FILE (not a dir) is an OSError; the
    # helper must swallow it and report False, never raise.
    bad_parent = tmp_path / "afile"
    bad_parent.write_text("x")
    ok = fl._persist_promoted(
        ProposerCorrection("finance", SIGNAL_TOOL_MISSING, "t", 3, "g"),
        path=bad_parent / "nested" / "p.ndjson",
    )
    assert ok is False


def test_review_and_promote_skips_on_persist_failure(on, monkeypatch):
    for pack in ("finance_a", "finance_b", "finance_c"):
        fl.record_outcome(pack, SIGNAL_TOOL_MISSING, detail="web_search")
    monkeypatch.setattr(fl, "_persist_promoted", lambda *a, **k: False)

    class _Accept:
        def evaluate(self, c):
            import types
            return types.SimpleNamespace(promote=True)

    # A failed persist must not be counted as promoted (and must not crash).
    assert fl.review_and_promote(min_support=3, controller=_Accept()) == []
