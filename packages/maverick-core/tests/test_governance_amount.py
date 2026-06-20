"""Amount-aware authorization in governance (finance-agent-suite §2.3)."""
from __future__ import annotations

from maverick.governance import Decision, Policy, _amount_table, evaluate


def test_require_human_above_threshold():
    pol = Policy(require_human_above={"release_payment": 5000})
    assert evaluate("release_payment", amount=6000, policy=pol).decision is Decision.REQUIRE_HUMAN
    assert evaluate("release_payment", amount=4000, policy=pol).decision is Decision.ALLOW
    # exactly at the threshold is allowed (strictly above triggers)
    assert evaluate("release_payment", amount=5000, policy=pol).decision is Decision.ALLOW


def test_deny_above_threshold():
    pol = Policy(deny_above={"wire_transfer": 50000})
    assert evaluate("wire_transfer", amount=60000, policy=pol).decision is Decision.DENY
    assert evaluate("wire_transfer", amount=40000, policy=pol).decision is Decision.ALLOW


def test_wildcard_threshold_applies_to_all_actions():
    pol = Policy(require_human_above={"*": 1000})
    assert evaluate("any_action", amount=2000, policy=pol).decision is Decision.REQUIRE_HUMAN
    assert evaluate("any_action", amount=500, policy=pol).decision is Decision.ALLOW


def test_wildcard_floor_binds_lower_than_exact_action():
    # Strictest-wins: a "*" catch-all is a FLOOR, so a per-action key can only
    # tighten it, never loosen it (audit round 15). release_payment is gated at
    # min(10000, 1000)=1000, NOT its own higher 10000.
    pol = Policy(require_human_above={"*": 1000, "release_payment": 10000})
    # $5k release_payment trips the $1k catch-all floor (used to ALLOW under the
    # higher per-action threshold -- the money-movement bypass this closes).
    assert evaluate("release_payment", amount=5000, policy=pol).decision is Decision.REQUIRE_HUMAN
    # Below the floor: still allowed.
    assert evaluate("release_payment", amount=500, policy=pol).decision is Decision.ALLOW
    # A different action falls back to the same wildcard floor.
    assert evaluate("post_note", amount=5000, policy=pol).decision is Decision.REQUIRE_HUMAN


def test_exact_action_tighter_than_wildcard_still_applies():
    # A per-action key STRICTER than "*" binds (min picks it): $200 wire gated.
    pol = Policy(require_human_above={"*": 5000, "wire_transfer": 100})
    assert evaluate("wire_transfer", amount=200, policy=pol).decision is Decision.REQUIRE_HUMAN
    # A non-wire action uses the looser $5k catch-all.
    assert evaluate("post_note", amount=200, policy=pol).decision is Decision.ALLOW


def test_deny_above_beats_require_human_above():
    pol = Policy(deny_above={"a": 100}, require_human_above={"a": 10})
    assert evaluate("a", amount=200, policy=pol).decision is Decision.DENY


def test_no_amount_no_gating():
    pol = Policy(require_human_above={"*": 1}, deny_above={"*": 1})
    # amount omitted -> threshold gates don't fire (back-compat)
    assert evaluate("anything", policy=pol).decision is Decision.ALLOW


def test_reason_includes_amount_and_currency():
    pol = Policy(require_human_above={"pay": 5000})
    v = evaluate("pay", amount=9000, currency="USD", policy=pol)
    assert "9000" in v.reason and "USD" in v.reason
    assert v.rule == "require_human_above"


def test_amount_table_coercion():
    assert _amount_table({"a": 5, "b": 1.5}) == {"a": 5.0, "b": 1.5}
    assert _amount_table(1000) == {"*": 1000.0}      # bare number -> wildcard
    assert _amount_table(True) == {}                 # bool is not an amount
    assert _amount_table({"a": "nope"}) == {}        # non-numeric dropped
    assert _amount_table(None) == {}


def test_empty_policy_with_thresholds_not_empty():
    assert not Policy(require_human_above={"*": 1}).is_empty()
    assert Policy().is_empty()


def test_threshold_composes_with_capability_deny():
    from maverick.capability import Capability
    cap = Capability(principal="p", deny_tools=frozenset({"release_payment"}))
    pol = Policy(require_human_above={"release_payment": 5000})
    # capability deny wins over the (lower-precedence) amount gate
    v = evaluate("release_payment", amount=10, capability=cap, policy=pol)
    assert v.decision is Decision.DENY and v.rule == "capability"
