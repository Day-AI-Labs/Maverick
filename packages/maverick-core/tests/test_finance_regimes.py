"""Finance compliance-regime packs (finance-agent-suite §5)."""
from __future__ import annotations

from maverick.finance.regimes import (
    REGIMES,
    compile_policy,
    list_regimes,
    union_policies,
)
from maverick.governance import Decision, Policy, evaluate


def test_all_regimes_present():
    assert set(REGIMES) == {
        "sox", "coso", "gaap", "pci", "glba", "aml", "sec", "irs"}
    assert len(list_regimes()) == 8


def test_sox_gates_money_movement():
    pol = compile_policy(["sox"])
    assert "post_journal_entry" in pol.require_human_actions
    assert "release_payment" in pol.require_human_actions
    assert pol.require_human_min_risk == "high"
    assert evaluate("release_payment", policy=pol).decision is Decision.REQUIRE_HUMAN


def test_compile_policy_normalizes_regime_key_case():
    # A mis-cased KNOWN regime key must not silently compile to no enforcement.
    caps = compile_policy(["SOX", "AML"])
    low = compile_policy(["sox", "aml"])
    assert caps.require_human_actions == low.require_human_actions
    assert "release_payment" in caps.require_human_actions
    assert compile_policy([" Sox "]).require_human_actions \
        == compile_policy(["sox"]).require_human_actions


def test_sec_and_irs_gate_filing():
    assert "file_with_sec" in compile_policy(["sec"]).require_human_actions
    irs = compile_policy(["irs"])
    assert {"file_return", "remit_tax"} <= set(irs.require_human_actions)


def test_union_is_strictest_wins_thresholds():
    a = Policy(deny_above={"pay": 100}, require_human_min_risk="high")
    b = Policy(deny_above={"pay": 50}, require_human_min_risk="medium")
    u = union_policies([a, b])
    assert u.deny_above["pay"] == 50              # lowest threshold wins
    assert u.require_human_min_risk == "medium"   # stricter floor wins


def test_deny_beats_require_human_in_union():
    a = Policy(deny_actions=frozenset({"x"}))
    b = Policy(require_human_actions=frozenset({"x"}))
    u = union_policies([a, b])
    assert "x" in u.deny_actions
    assert "x" not in u.require_human_actions


def test_multi_regime_union_covers_all():
    pol = compile_policy(["sox", "aml", "sec", "irs"])
    for action in ("release_payment", "wire_transfer", "file_with_sec", "remit_tax"):
        v = evaluate(action, policy=pol)
        assert v.decision is Decision.REQUIRE_HUMAN, action


def test_unknown_key_ignored_and_empty():
    assert compile_policy(["bogus"]).is_empty()
    assert compile_policy([]).is_empty()


def test_evidence_only_regimes_have_empty_policy():
    # COSO / PCI / GLBA are evidence frameworks; enforcement is elsewhere.
    for k in ("coso", "pci", "glba"):
        assert REGIMES[k].policy.is_empty()
        assert REGIMES[k].asserts  # but they describe what they cover
