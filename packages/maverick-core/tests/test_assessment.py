"""Compliance assessment engine: templates, scoring, persistence, CLI."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from maverick.cli import main


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # Keep saved assessments off the real ~/.maverick.
    from maverick import paths
    monkeypatch.setattr(paths, "maverick_home", lambda: tmp_path / "home")


def test_templates_registered_and_looked_up():
    from maverick.assessment import get_template, list_templates

    types = {t.type for t in list_templates()}
    # Core compliance templates + the finance suite (finance-agent-suite §6).
    assert types == {
        "pia", "aira", "vendor_risk",
        "sox_control", "fraud_risk", "itgc", "credit_risk", "close_readiness",
    }
    assert get_template("VENDOR_RISK").title == "Vendor Risk Assessment"  # case-insensitive
    assert get_template("nope") is None


def test_clean_answers_are_minimal_risk():
    from maverick.assessment import AssessmentSession, get_template

    tpl = get_template("pia")
    s = AssessmentSession(type="pia", subject="Marketing emails")
    for q in tpl.questions:
        s.record(q.id, "no" if q.risk_answer == "yes" else "yes")  # the safe answer
    r = s.evaluate()
    assert r.risk_rating == "minimal"
    assert r.findings == []
    assert r.answered == r.total


def test_risky_answers_score_findings_and_roll_up():
    from maverick.assessment import AssessmentSession

    s = AssessmentSession(type="vendor_risk", subject="Acme Corp")
    s.record("vr_dpa", "no")                  # high (risk answer)
    s.record("vr_soc2", "yes")                # safe -> no finding
    s.record("vr_breach_history", "yes")      # medium (risk answer is "yes")
    s.record("vr_business_continuity", "unknown")  # low, unverified
    r = s.evaluate()

    assert r.risk_rating == "high"            # max severity among findings
    kinds = {f.question_id: f.kind for f in r.findings}
    assert kinds["vr_dpa"] == "risk"
    assert kinds["vr_breach_history"] == "risk"
    assert kinds["vr_business_continuity"] == "unverified"
    assert "vr_soc2" not in kinds
    assert r.answered == 3                     # yes/no/na count; unknown does not


def test_record_rejects_bad_answer_and_unknown_question():
    from maverick.assessment import AssessmentSession

    s = AssessmentSession(type="aira", subject="Resume screener")
    with pytest.raises(ValueError):
        s.record("aira_purpose", "maybe")
    with pytest.raises(KeyError):
        s.record("does_not_exist", "yes")


def test_assessment_session_ids_are_unique_for_rapid_creation():
    from maverick.assessment import AssessmentSession

    ids = {AssessmentSession(type="pia", subject=f"Subject {i}").id for i in range(1000)}

    assert len(ids) == 1000


def test_persistence_round_trip():
    from maverick.assessment import (
        AssessmentSession,
        list_saved,
        load_saved,
        save_session,
    )

    s = AssessmentSession(type="vendor_risk", subject="Acme Corp")
    s.record("vr_dpa", "no")
    path = save_session(s)
    assert path.exists()

    rows = list_saved()
    assert len(rows) == 1
    assert rows[0]["subject"] == "Acme Corp"
    assert rows[0]["risk_rating"] == "high"

    data = load_saved(s.id)
    assert data["type"] == "vendor_risk"
    assert data["result"]["findings"][0]["question_id"] == "vr_dpa"


def test_cli_assess_flow(tmp_path):
    from maverick.assessment import list_saved

    runner = CliRunner()
    assert runner.invoke(main, ["assess", "templates"]).exit_code == 0

    q = runner.invoke(main, ["assess", "questions", "pia"])
    assert q.exit_code == 0 and "pia_security" in q.output

    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"vr_dpa": "no", "vr_soc2": "yes"}))
    scored = runner.invoke(
        main,
        ["assess", "score", "vendor_risk", "--subject", "Acme", "--answers", str(answers)],
    )
    assert scored.exit_code == 0
    assert "HIGH" in scored.output and "saved:" in scored.output

    lst = runner.invoke(main, ["assess", "list"])
    assert lst.exit_code == 0 and "Acme" in lst.output

    shown = runner.invoke(main, ["assess", "show", list_saved()[0]["id"]])
    assert shown.exit_code == 0 and "Acme" in shown.output
