"""Governance-posture audit of the specialist roster.

domains-lint answers "is each pack well-formed?"; domains-audit answers "what
can these agents do, and what stops them?" -- the inventory a GRC reviewer
needs. These tests pin the load-bearing invariant (no drafting agent reaches a
state-mutator) and the report shape.
"""
from __future__ import annotations

from click.testing import CliRunner
from maverick.domain import DomainProfile, builtin_dir, load_domains
from maverick.domain_audit import (
    audit_profile,
    audit_roster,
    summarize,
    to_json,
)

_BUILTIN = load_domains(builtin_dir())


def test_audit_captures_governance_posture():
    p = _BUILTIN["finance_ap"]
    a = audit_profile(p)
    assert a.suite == "finance"
    assert a.compartment.startswith("finance")
    assert a.is_builder is False
    assert a.reachable_dangerous == []          # a drafting agent reaches no mutator
    assert "release_payment" in a.denied_irreversible
    assert a.human_gate in ("approval", "review")
    assert a.deliverable                        # declares a deliverable
    assert a.n_refusals >= 2                     # at least the universal refusals


def test_roster_has_no_drafting_agent_reaching_a_mutator():
    # The headline provable-governance number across all 1,118 packs.
    s = summarize(audit_roster(_BUILTIN))
    assert s["packs"] >= 1000
    assert s["drafting_agents_reaching_a_mutator"] == 0
    assert s["packs_with_deliverable"] == s["packs"]


def test_human_gate_prefers_approval_over_review():
    from maverick.domain import OutputContract, WorkflowStep
    p = DomainProfile(
        name="x", allow_tools=["read_file"], deny_tools=["shell", "write_file"],
        max_risk="low",
        output=OutputContract(deliverable="d", consumers=["o"], gate="review"),
        workflow=[WorkflowStep("commit", gate="approval")],
    )
    assert audit_profile(p).human_gate == "approval"


def test_builder_is_flagged_as_builder_not_dangerous():
    builders = [a for a in audit_roster(_BUILTIN) if a.is_builder]
    assert builders, "expected coding builders in the roster"
    for a in builders:
        # A builder legitimately reaches shell/code_exec; it is recorded as a
        # builder, and the summary excludes it from the drafting-agent invariant.
        assert "self_edit" not in a.reachable_dangerous  # the one floor never relaxes


def test_json_export_is_well_formed():
    doc = to_json(audit_roster(_BUILTIN))
    assert set(doc) == {"summary", "packs"}
    assert len(doc["packs"]) == len(_BUILTIN)
    row = doc["packs"][0]
    for key in ("name", "suite", "compartment", "max_risk", "reachable_dangerous",
                "n_refusals", "human_gate", "deliverable"):
        assert key in row


def test_cli_reports_and_exits_clean():
    from maverick.cli import main
    res = CliRunner().invoke(main, ["domains-audit"])
    assert res.exit_code == 0, res.output
    assert "must be 0" in res.output
    assert "with a declared deliverable" in res.output


def test_cli_json_export(tmp_path):
    import json

    from maverick.cli import main
    out = tmp_path / "audit.json"
    res = CliRunner().invoke(main, ["domains-audit", "--json", str(out)])
    assert res.exit_code == 0, res.output
    doc = json.loads(out.read_text())
    assert doc["summary"]["drafting_agents_reaching_a_mutator"] == 0
