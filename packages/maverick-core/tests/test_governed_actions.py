"""Governed Actions: typed ops + simulate-before-commit + tamper-evident lineage."""
from __future__ import annotations

import dataclasses

import pytest
from maverick.governed_actions import ActionError, ActionSpec, GovernedActions


def _registry(applied):
    ga = GovernedActions()
    ga.register(ActionSpec(
        name="set_status", params={"id": int, "status": str}, risk="medium",
        simulate=lambda p: f"would set {p['id']} -> {p['status']}",
        apply=lambda p: (applied.append((p["id"], p["status"])), f"set {p['id']}")[1]))
    return ga


def test_simulate_previews_without_side_effects():
    applied: list = []
    ga = _registry(applied)
    pv = ga.simulate("set_status", {"id": 1, "status": "done"})
    assert "would set 1 -> done" in pv.effect
    assert applied == []                 # simulate must NOT apply
    assert pv.requires_approval is False  # medium < default floor (high)


def test_commit_applies_and_records_lineage():
    applied: list = []
    ga = _registry(applied)
    assert ga.commit("set_status", {"id": 1, "status": "done"}) == "set 1"
    assert applied == [(1, "done")]
    assert len(ga.lineage) == 1
    assert ga.verify_lineage().startswith("VALID")


def test_typing_is_enforced():
    ga = GovernedActions()
    ga.register(ActionSpec("a", {"x": int}, apply=lambda p: "ok"))
    with pytest.raises(ActionError, match="missing"):
        ga.commit("a", {})
    with pytest.raises(ActionError, match="must be int"):
        ga.commit("a", {"x": "nope"})


def test_high_risk_requires_an_approver():
    ga = GovernedActions()
    ga.register(ActionSpec("delete", {"id": int}, risk="high", apply=lambda p: "deleted"))
    with pytest.raises(ActionError, match="requires an approver"):
        ga.commit("delete", {"id": 1})            # high-risk, no approver -> refused
    assert ga.commit("delete", {"id": 1}, approver="alice") == "deleted"
    assert ga.lineage[-1].approver == "alice"


def test_unknown_action_and_bad_risk_rejected():
    ga = GovernedActions()
    with pytest.raises(ActionError, match="unknown action"):
        ga.simulate("nope", {})
    with pytest.raises(ValueError):
        ActionSpec("a", {}, risk="nuclear")


def test_lineage_detects_tampering():
    ga = GovernedActions()
    ga.register(ActionSpec("a", {"x": int}, apply=lambda p: "ok"))
    ga.commit("a", {"x": 1})
    ga.commit("a", {"x": 2})
    assert ga.verify_lineage().startswith("VALID")
    # edit a recorded input -> the chain must break at that link
    ga.lineage[0] = dataclasses.replace(ga.lineage[0], params_json='{"x": 999}')
    assert ga.verify_lineage().startswith("BROKEN")


def test_trace_is_the_decision_lineage():
    ga = GovernedActions()
    ga.register(ActionSpec("recommend", {"q": str}, risk="low",
                           simulate=lambda p: "preview", apply=lambda p: "ANSWER"))
    ga.commit("recommend", {"q": "x"}, sources=("doc1",), skills=("skill-a",))
    t = ga.trace()
    assert t["action"] == "recommend"
    assert t["result"] == "ANSWER"
    assert t["sources"] == ["doc1"] and t["skills"] == ["skill-a"]
