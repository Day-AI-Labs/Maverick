"""The compliance-auditor agent: audit envelope (research + controls + assessment
+ live-posture evidence) and the never-certify persona."""
from __future__ import annotations

import asyncio

from maverick import assessment
from maverick.assessment import (
    AssessmentSession,
    _compliance_auditor_tools,
    build_compliance_auditor_agent,
)
from maverick.tools import Tool, ToolRegistry


async def _noop(args):
    return "ok"


def _tool(name):
    return Tool(name=name, description=name,
                input_schema={"type": "object", "properties": {}}, fn=_noop)


def test_auditor_envelope_keeps_evidence_drops_mutating():
    base = ToolRegistry()
    for n in ("read_file", "web_search", "knowledge_search", "find_controls",
              "http_fetch", "shell", "write_file"):
        base.register(_tool(n))
    names = {t.name for t in _compliance_auditor_tools(base, AssessmentSession()).all()}
    # research + control catalog + assessment engine + the live-posture evidence tool
    assert {"read_file", "web_search", "knowledge_search", "find_controls",
            "start_assessment", "finalize_assessment", "deployment_posture"} <= names
    # mutating / outward (incl. the exfil-capable http_fetch) excluded
    assert names.isdisjoint({"shell", "write_file", "http_fetch"})


def test_deployment_posture_reports_live_control_state(monkeypatch):
    from dataclasses import dataclass

    from maverick.tools.posture_tools import posture_tools

    @dataclass
    class _C:
        control: str
        regulation: str
        status: str
        detail: str
        framework: str = "eu"

    monkeypatch.setattr(
        "maverick.compliance.compliance_report",
        lambda: [_C("Encryption at rest", "GDPR Art. 32", "active", "AES-256-GCM")],
    )
    out = asyncio.run(posture_tools()[0].fn({}))
    assert "Encryption at rest" in out and "[active]" in out


def test_persona_audits_and_never_certifies():
    p = assessment.COMPLIANCE_AUDITOR_PERSONA.lower()
    assert "deployment_posture" in p and "audit-readiness" in p
    assert "unknown" in p                         # honest gaps, not guessed passes
    assert "never declare" in p and "certified" in p
    assert callable(build_compliance_auditor_agent)
