"""Assessment tools -- the compliance assessor agent's hands.

Bound to a shared :class:`maverick.assessment.AssessmentSession`: the agent picks
an assessment type + subject (``start_assessment``), answers each question from
the documents and context it was given (``answer_question``), and produces the
scored result (``finalize_assessment``) for a human to sign off. The agent never
approves the assessment itself -- it drafts the findings.

A thin layer over :mod:`maverick.assessment`, exactly as ``intake_tools`` sits on
:mod:`maverick.intake`.
"""
from __future__ import annotations

from . import Tool


def assessment_tools(session) -> list[Tool]:
    from ..assessment import (
        get_template,
        list_templates,
        render_questions_text,
        save_session,
    )

    async def _list(args: dict) -> str:
        return "Available assessments:\n" + "\n".join(
            f"  {t.type}: {t.title} ({t.framework})" for t in list_templates()
        )

    async def _start(args: dict) -> str:
        atype = str(args.get("type", "")).strip().lower()
        subject = str(args.get("subject", "")).strip()
        tpl = get_template(atype)
        if tpl is None:
            return (f"ERROR: unknown assessment type {atype!r}; "
                    "call list_assessments first.")
        if not subject:
            return "ERROR: 'subject' is required (what you are assessing)."
        session.type = atype
        session.subject = subject
        session.answers.clear()
        return (f"Started {tpl.title} of {subject!r}. Answer each question with "
                f"answer_question (answer: yes/no/na/unknown):\n\n"
                f"{render_questions_text(tpl)}")

    async def _answer(args: dict) -> str:
        if not session.type:
            return "ERROR: call start_assessment first."
        qid = str(args.get("question_id", "")).strip()
        answer = str(args.get("answer", "")).strip()
        note = str(args.get("note", "")).strip()
        try:
            session.record(qid, answer, note)
        except (KeyError, ValueError) as e:
            return f"ERROR: {e}"
        return f"Recorded {qid} = {answer}. {len(session.answers)} answered so far."

    async def _finalize(args: dict) -> str:
        if not session.type:
            return "ERROR: call start_assessment first."
        result = session.evaluate()
        try:
            save_session(session)
        except Exception as e:  # producing the result must not fail on a write error
            return f"Scored, but could not save ({type(e).__name__}): see findings below."
        lines = [
            f"{result.subject}: risk {result.risk_rating.upper()} "
            f"({result.answered}/{result.total} answered, "
            f"{len(result.findings)} finding(s))."
        ]
        for f in result.findings:
            tag = "UNVERIFIED" if f.kind == "unverified" else f.severity.upper()
            lines.append(f"  [{tag}] {f.question} -> {f.recommendation}")
        lines.append("DRAFT for a human reviewer to sign off -- you do not approve it.")
        return "\n".join(lines)

    return [
        Tool(
            name="list_assessments",
            description="List the assessment types you can conduct (pia, aira, "
                        "vendor_risk).",
            input_schema={"type": "object", "properties": {}},
            fn=_list,
        ),
        Tool(
            name="start_assessment",
            description="Begin an assessment of a subject. Returns the questionnaire "
                        "to answer.",
            input_schema={
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "description": "pia | aira | vendor_risk"},
                    "subject": {"type": "string",
                                "description": "what is being assessed"},
                },
                "required": ["type", "subject"],
            },
            fn=_start,
        ),
        Tool(
            name="answer_question",
            description="Record one answer. answer is yes/no/na, or 'unknown' when "
                        "you cannot verify it from the evidence (do not guess).",
            input_schema={
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "answer": {"type": "string",
                               "enum": ["yes", "no", "na", "unknown"]},
                    "note": {"type": "string"},
                },
                "required": ["question_id", "answer"],
            },
            fn=_answer,
        ),
        Tool(
            name="finalize_assessment",
            description="Score the answers into findings + a risk rating and save "
                        "the draft for human review.",
            input_schema={"type": "object", "properties": {}},
            fn=_finalize,
        ),
    ]
