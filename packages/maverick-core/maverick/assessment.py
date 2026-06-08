"""Compliance assessment engine -- conduct PIAs, AIRAs, Vendor Risk Assessments.

This is the OneTrust-style assessment core: a structured questionnaire is run
against a *subject* (a processing activity, an AI system, a vendor), each answer
is scored, and the result is a completed assessment with **findings** and an
overall **risk rating**. Distinct from ``maverick ropa`` / ``dpia`` / ``ai-act``,
which generate a scaffold from Maverick's *own* deployment config -- this assesses
an arbitrary third-party subject.

A template is plain data (:class:`AssessmentTemplate` -> :class:`Question`), so
new assessment types are added by appending to :data:`TEMPLATES`, not by writing
code. The frameworks built in here:

  - ``pia``         -- Privacy Impact Assessment (ISO 29134 / GDPR Art. 35 flavour)
  - ``aira``        -- AI Risk Assessment (NIST AI RMF / EU AI Act flavour)
  - ``vendor_risk`` -- Third-party / vendor risk assessment (TPRM flavour)
  - ``hipaa``       -- HIPAA Security Rule safeguards (45 CFR Part 164)
  - ``soc2``        -- SOC 2 Trust Services Criteria readiness (AICPA)
  - ``pci_dss``     -- PCI DSS v4.0 cardholder-data controls

The scoring is a transparent max-severity rollup: a question's *risk answer*
raises a finding at its severity; ``unknown`` raises an "unverified" finding
(diligence gap); ``na`` / the safe answer clear it. Overall rating = the highest
finding severity present.

The conversational assessor agent (``build_assessment_agent``) and its tools are
a thin layer on top of this engine, exactly as the intake agent sits on
:mod:`maverick.intake`.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Answer vocabulary. ``na`` = not applicable (clears the question); ``unknown`` =
# the assessor could not confirm it (a diligence gap, scored as "unverified").
ANSWERS = ("yes", "no", "na", "unknown")
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def _new_session_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class Question:
    id: str
    section: str
    text: str
    risk_answer: str          # the answer that indicates risk: "yes" or "no"
    severity: str             # "low" | "medium" | "high"
    guidance: str = ""        # how to remediate if this is a finding


@dataclass(frozen=True)
class AssessmentTemplate:
    type: str
    title: str
    framework: str
    description: str
    questions: tuple[Question, ...]

    def question(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)


@dataclass(frozen=True)
class Finding:
    question_id: str
    section: str
    question: str
    severity: str
    answer: str
    kind: str                 # "risk" (gave the risky answer) | "unverified" (unknown)
    recommendation: str


@dataclass
class AssessmentResult:
    type: str
    subject: str
    risk_rating: str          # "high" | "medium" | "low" | "minimal"
    findings: list[Finding]
    answered: int
    total: int


def _q(qid, section, text, risk_answer, severity, guidance=""):
    return Question(qid, section, text, risk_answer, severity, guidance)


# --- Built-in assessment templates ----------------------------------------

_PIA = AssessmentTemplate(
    type="pia",
    title="Privacy Impact Assessment",
    framework="ISO 29134 / GDPR Art. 35",
    description="Assess the privacy risk of a processing activity.",
    questions=(
        _q("pia_necessity", "Necessity",
           "Is the personal data collected strictly necessary for the stated purpose?",
           "no", "high", "Minimize collection to what the purpose requires (Art. 5(1)(c))."),
        _q("pia_lawful_basis", "Lawful basis",
           "Is there a documented lawful basis for the processing (Art. 6)?",
           "no", "high", "Identify and record a lawful basis before processing."),
        _q("pia_special_category", "Lawful basis",
           "Does it process special-category data (health, biometrics, etc.) without an Art. 9 condition?",
           "yes", "high", "Establish an Art. 9 condition or stop processing special-category data."),
        _q("pia_transparency", "Transparency",
           "Are data subjects informed of the processing (privacy notice, Art. 13/14)?",
           "no", "medium", "Provide a clear privacy notice at or before collection."),
        _q("pia_rights", "Data-subject rights",
           "Can data subjects exercise access / erasure / portability rights?",
           "no", "medium", "Wire up DSAR handling (access, erasure, portability)."),
        _q("pia_retention", "Storage limitation",
           "Is there a defined retention period after which the data is deleted?",
           "no", "medium", "Set and enforce a retention schedule (Art. 5(1)(e))."),
        _q("pia_security", "Security",
           "Is the personal data encrypted in transit and at rest?",
           "no", "high", "Encrypt in transit (TLS) and at rest (Art. 32)."),
        _q("pia_transfers", "International transfers",
           "Is personal data transferred outside the EU/EEA without a Chapter V safeguard?",
           "yes", "high", "Put an adequacy decision or SCCs in place before transferring."),
        _q("pia_processors", "Processors",
           "Is every processor bound by a data-processing agreement (Art. 28)?",
           "no", "medium", "Execute an Art. 28 DPA with each processor."),
        _q("pia_automated", "Automated decisions",
           "Does it make solely-automated decisions with legal/significant effects (Art. 22)?",
           "yes", "medium", "Add human review or an Art. 22 exception/safeguard."),
    ),
)

_AIRA = AssessmentTemplate(
    type="aira",
    title="AI Risk Assessment",
    framework="NIST AI RMF / EU AI Act",
    description="Assess the risk of an AI system.",
    questions=(
        _q("aira_purpose", "Governance",
           "Is the AI system's purpose and intended use documented?",
           "no", "medium", "Document intended purpose, scope, and out-of-scope uses."),
        _q("aira_prohibited", "Governance",
           "Could the system fall under an EU AI Act prohibited practice (Art. 5)?",
           "yes", "high", "Stop -- prohibited uses cannot be placed on the market."),
        _q("aira_high_risk", "Governance",
           "Is the use case in a high-risk domain (Annex III) without a conformity assessment?",
           "yes", "high", "Run an Annex III conformity assessment before deployment."),
        _q("aira_transparency", "Transparency",
           "Are users informed they are interacting with / subject to AI (Art. 50)?",
           "no", "medium", "Disclose AI use to affected users."),
        _q("aira_oversight", "Human oversight",
           "Is there meaningful human oversight of the system's decisions (Art. 14)?",
           "no", "high", "Add a human-in-the-loop / override mechanism."),
        _q("aira_bias", "Fairness",
           "Has the system been evaluated for bias across affected groups?",
           "no", "high", "Run a bias/fairness evaluation on representative data."),
        _q("aira_accuracy", "Robustness",
           "Are accuracy / robustness metrics measured and monitored in production?",
           "no", "medium", "Define accuracy thresholds and monitor for drift."),
        _q("aira_data_governance", "Data governance",
           "Is the training/operating data of known provenance and lawful to use?",
           "no", "high", "Establish data provenance and processing lawfulness."),
        _q("aira_security", "Security",
           "Is the system protected against adversarial / prompt-injection attacks?",
           "no", "medium", "Add input validation and adversarial testing."),
        _q("aira_logging", "Accountability",
           "Are the system's decisions logged for traceability (Art. 12)?",
           "no", "medium", "Enable tamper-evident decision logging."),
    ),
)

_VENDOR_RISK = AssessmentTemplate(
    type="vendor_risk",
    title="Vendor Risk Assessment",
    framework="Third-party risk management (TPRM)",
    description="Assess the security and privacy risk of a third-party vendor.",
    questions=(
        _q("vr_soc2", "Certifications",
           "Does the vendor hold a current SOC 2 Type II (or ISO 27001) report?",
           "no", "high", "Request the report; treat absence as elevated risk."),
        _q("vr_dpa", "Contractual",
           "Is a data-processing agreement (DPA) in place with the vendor?",
           "no", "high", "Execute a DPA before sharing personal data (Art. 28)."),
        _q("vr_encryption", "Security",
           "Does the vendor encrypt your data in transit and at rest?",
           "no", "high", "Require TLS in transit and encryption at rest."),
        _q("vr_access_control", "Security",
           "Does the vendor enforce MFA and least-privilege access to your data?",
           "no", "medium", "Require MFA and role-based access controls."),
        _q("vr_breach_history", "History",
           "Has the vendor had a reported data breach in the last 24 months?",
           "yes", "medium", "Review the breach, root cause, and remediation."),
        _q("vr_subprocessors", "Subprocessors",
           "Does the vendor disclose its subprocessors and notify of changes?",
           "no", "medium", "Require a subprocessor list and change notification."),
        _q("vr_data_location", "Data residency",
           "Is your data stored or processed outside the EU/EEA without safeguards?",
           "yes", "high", "Confirm data location and Chapter V transfer safeguards."),
        _q("vr_incident_sla", "Incident response",
           "Does the contract commit the vendor to a breach-notification timeline?",
           "no", "medium", "Require a defined breach-notification SLA (e.g. 72h)."),
        _q("vr_deletion", "Offboarding",
           "Will the vendor return or delete your data on contract termination?",
           "no", "medium", "Require data return/deletion terms at offboarding."),
        _q("vr_business_continuity", "Resilience",
           "Does the vendor have a tested business-continuity / DR plan?",
           "no", "low", "Request BC/DR evidence proportional to criticality."),
    ),
)

# --- Finance assessment templates (finance-agent-suite §6) -----------------

_SOX_CONTROL = AssessmentTemplate(
    type="sox_control",
    title="SOX Control Assessment",
    framework="SOX §404 / COSO",
    description="Test the design + operating effectiveness of an ICFR control.",
    questions=(
        _q("sox_evidence", "Operating effectiveness",
           "Is the control's operating effectiveness evidenced for the period?",
           "no", "high", "Obtain and retain sampled evidence of each execution."),
        _q("sox_sod", "Segregation of duties",
           "Is there an SoD conflict in the roles responsible for this control?",
           "yes", "high", "Separate the incompatible duties (record/authorize/custody/reconcile)."),
        _q("sox_design", "Control design",
           "Does the control's design address the risk/assertion it is mapped to?",
           "no", "high", "Redesign the control to cover the assertion (existence/completeness/...)."),
        _q("sox_frequency", "Operation",
           "Did the control operate at its defined frequency throughout the period?",
           "no", "medium", "Remediate gaps; assess whether a deficiency must be reported."),
        _q("sox_review", "Review",
           "Is the control's execution independently reviewed and signed off?",
           "no", "medium", "Add an independent reviewer with evidenced sign-off."),
        _q("sox_itdependency", "IT dependency",
           "Does the control rely on a report/system whose ITGCs are untested?",
           "yes", "medium", "Test the supporting ITGCs (access, change, completeness)."),
    ),
)

_FRAUD_RISK = AssessmentTemplate(
    type="fraud_risk",
    title="Fraud Risk Assessment",
    framework="ACFE / SAS 99",
    description="Assess fraud exposure in a financial process.",
    questions=(
        _q("fraud_vendor_create_approve", "Segregation",
           "Can one person both create and approve a vendor?",
           "yes", "high", "Split vendor creation from approval (SoD)."),
        _q("fraud_bank_change", "Master data",
           "Are vendor/employee bank-detail changes independently reviewed?",
           "no", "high", "Require out-of-band verification for every bank-detail change."),
        _q("fraud_dup_payment", "Payments",
           "Are duplicate and split payments detected before release?",
           "no", "high", "Run duplicate/split detection on every payment batch."),
        _q("fraud_ghost", "Master data",
           "Is the vendor/employee master periodically checked for ghost entries?",
           "no", "medium", "Reconcile master data to active relationships regularly."),
        _q("fraud_override", "Management override",
           "Are manual journal entries and management overrides independently reviewed?",
           "no", "high", "Review all top-side/manual JEs for business rationale."),
        _q("fraud_whistleblower", "Detection",
           "Is there a confidential channel to report suspected fraud?",
           "no", "medium", "Provide an anonymous reporting hotline."),
    ),
)

_ITGC = AssessmentTemplate(
    type="itgc",
    title="IT General Controls Assessment",
    framework="COBIT / SOX ITGC",
    description="Assess access, change, and operations controls over a financial system.",
    questions=(
        _q("itgc_access_least_priv", "Access",
           "Is access to the posting/payment tool least-privileged and logged?",
           "no", "high", "Restrict to least privilege and log every use (capability + audit)."),
        _q("itgc_access_review", "Access",
           "Is system access reviewed periodically and revoked on role change?",
           "no", "medium", "Run periodic access recertification with evidenced removal."),
        _q("itgc_change_mgmt", "Change",
           "Are changes to the financial system tested and approved before release?",
           "no", "high", "Require tested, approved, segregated change management."),
        _q("itgc_audit_trail", "Operations",
           "Is there a complete, tamper-evident audit trail of transactions?",
           "no", "high", "Enable the signed append-only audit log and verify it."),
        _q("itgc_backup", "Operations",
           "Are backups taken and restoration periodically tested?",
           "no", "medium", "Schedule backups and test restores on a cadence."),
        _q("itgc_segregation", "Access",
           "Does any one identity hold incompatible system duties?",
           "yes", "high", "Separate incompatible system roles (SoD)."),
    ),
)

_CREDIT_RISK = AssessmentTemplate(
    type="credit_risk",
    title="Customer Credit Risk Assessment",
    framework="CECL / internal credit policy",
    description="Assess the credit risk of a customer / receivable.",
    questions=(
        _q("credit_past_due", "Aging",
           "Is the customer past terms by more than 90 days?",
           "yes", "high", "Escalate to collections; reassess the credit limit."),
        _q("credit_limit_breach", "Exposure",
           "Does current exposure exceed the approved credit limit?",
           "yes", "high", "Hold new orders pending a credit review."),
        _q("credit_deteriorating", "Monitoring",
           "Has the customer's payment behaviour deteriorated recently?",
           "yes", "medium", "Tighten terms and increase the allowance estimate."),
        _q("credit_concentration", "Concentration",
           "Does this customer represent a concentration risk (>10% of AR)?",
           "yes", "medium", "Diversify or secure the exposure (guarantee/insurance)."),
        _q("credit_secured", "Mitigation",
           "Is the exposure unsecured with no guarantee or insurance?",
           "yes", "low", "Consider credit insurance or collateral for large balances."),
    ),
)

_CLOSE_READINESS = AssessmentTemplate(
    type="close_readiness",
    title="Period-Close Readiness Assessment",
    framework="internal close policy",
    description="Assess whether the books are ready to close for the period.",
    questions=(
        _q("close_bs_recon", "Reconciliation",
           "Are all balance-sheet accounts reconciled for the period?",
           "no", "high", "Complete and review all balance-sheet reconciliations."),
        _q("close_bank_rec", "Reconciliation",
           "Is every bank account reconciled to the ledger?",
           "no", "high", "Reconcile each bank account and clear stale items."),
        _q("close_accruals", "Completeness",
           "Are all known accruals and prepaids recorded?",
           "no", "medium", "Record outstanding accruals/prepaids before close."),
        _q("close_intercompany", "Intercompany",
           "Do intercompany balances net to zero across entities?",
           "no", "high", "Resolve intercompany mismatches before consolidation."),
        _q("close_flux", "Review",
           "Has flux/variance analysis been performed and explained?",
           "no", "medium", "Complete flux analysis with documented explanations."),
        _q("close_checklist", "Governance",
           "Is the close checklist complete with sign-offs?",
           "no", "medium", "Finish the checklist with evidenced approvals."),
    ),
)

_HIPAA = AssessmentTemplate(
    type="hipaa",
    title="HIPAA Security Rule Assessment",
    framework="HIPAA Security Rule (45 CFR Part 164)",
    description="Assess safeguards for electronic protected health information (ePHI).",
    questions=(
        _q("hipaa_risk_analysis", "Administrative safeguards",
           "Has a security risk analysis of ePHI been conducted and documented?",
           "no", "high", "Conduct + document a risk analysis (164.308(a)(1)(ii)(A))."),
        _q("hipaa_access_control", "Technical safeguards",
           "Is access to ePHI restricted by unique user IDs and role-based controls?",
           "no", "high", "Enforce unique user IDs + least-privilege access (164.312(a))."),
        _q("hipaa_encryption", "Technical safeguards",
           "Is ePHI encrypted in transit and at rest?",
           "no", "high", "Encrypt ePHI at rest and in transit, or document the "
           "addressable rationale (164.312(a)(2)(iv)/(e))."),
        _q("hipaa_audit_controls", "Technical safeguards",
           "Are audit controls in place to record and examine ePHI access?",
           "no", "high", "Enable audit logging of ePHI access + review (164.312(b))."),
        _q("hipaa_baa", "Administrative safeguards",
           "Is a Business Associate Agreement in place with every vendor that "
           "handles ePHI?",
           "no", "high", "Execute a BAA before a business associate touches ePHI "
           "(164.308(b))."),
        _q("hipaa_training", "Administrative safeguards",
           "Does the workforce receive periodic HIPAA security awareness training?",
           "no", "medium", "Provide + document security training (164.308(a)(5))."),
        _q("hipaa_contingency", "Administrative safeguards",
           "Is there a tested data-backup and disaster-recovery / contingency plan?",
           "no", "medium", "Maintain + test backup/contingency plans (164.308(a)(7))."),
        _q("hipaa_breach_notification", "Breach Notification Rule",
           "Is there a documented breach-notification process meeting the 60-day rule?",
           "no", "high", "Document breach assessment + notification (164.404, 60 days)."),
        _q("hipaa_minimum_necessary", "Privacy Rule",
           "Is the 'minimum necessary' standard applied to ePHI use and disclosure?",
           "no", "medium", "Limit ePHI use/disclosure to minimum necessary (164.502(b))."),
        _q("hipaa_integrity", "Technical safeguards",
           "Are mechanisms in place to ensure ePHI is not improperly altered or "
           "destroyed?",
           "no", "medium", "Implement integrity controls for ePHI (164.312(c))."),
    ),
)

_SOC2 = AssessmentTemplate(
    type="soc2",
    title="SOC 2 Readiness Assessment",
    framework="SOC 2 Trust Services Criteria (AICPA)",
    description="Assess readiness against the SOC 2 common/security criteria.",
    questions=(
        _q("soc2_access", "CC6 Logical access",
           "Are logical access controls (unique IDs, MFA, least privilege) enforced?",
           "no", "high", "Enforce MFA, RBAC, and unique IDs for all access (CC6.1)."),
        _q("soc2_change_mgmt", "CC8 Change management",
           "Are changes to production reviewed, tested, and approved before release?",
           "no", "high", "Adopt a documented change-management process (CC8.1)."),
        _q("soc2_risk", "CC3 Risk assessment",
           "Is a formal risk assessment performed and documented at least annually?",
           "no", "medium", "Run + document an annual risk assessment (CC3.1)."),
        _q("soc2_monitoring", "CC7 System operations",
           "Are systems monitored for security events with alerting?",
           "no", "high", "Deploy monitoring + alerting for anomalies (CC7.2)."),
        _q("soc2_incident", "CC7 System operations",
           "Is there a documented and tested incident-response plan?",
           "no", "high", "Document + test an incident-response plan (CC7.4)."),
        _q("soc2_vendor", "CC9 Risk mitigation",
           "Are vendors risk-assessed before onboarding and monitored over time?",
           "no", "medium", "Run vendor due diligence + ongoing monitoring (CC9.2)."),
        _q("soc2_encryption", "CC6 Logical access",
           "Is data encrypted in transit and at rest?",
           "no", "high", "Encrypt data in transit (TLS) and at rest (CC6.7)."),
        _q("soc2_backup", "A1 Availability",
           "Are backups performed and recovery periodically tested?",
           "no", "medium", "Perform backups + test restores periodically (A1.2)."),
        _q("soc2_policies", "CC1/CC2 Control environment",
           "Are information-security policies documented, approved, and communicated?",
           "no", "medium", "Maintain approved, communicated security policies "
           "(CC1.1/CC2.2)."),
        _q("soc2_deprovision", "CC6 Logical access",
           "Is access revoked promptly when personnel are terminated?",
           "no", "medium", "Automate timely deprovisioning on termination (CC6.2/6.3)."),
    ),
)

_PCI_DSS = AssessmentTemplate(
    type="pci_dss",
    title="PCI DSS Assessment",
    framework="PCI DSS v4.0",
    description="Assess controls protecting cardholder data (the CDE).",
    questions=(
        _q("pci_segmentation", "Req 1 Network security",
           "Is the cardholder data environment (CDE) segmented from other networks?",
           "no", "high", "Segment + firewall the CDE from untrusted networks (Req 1)."),
        _q("pci_defaults", "Req 2 Secure configuration",
           "Have vendor-default passwords and settings been changed on CDE systems?",
           "no", "high", "Remove/replace all vendor defaults before deployment (Req 2)."),
        _q("pci_stored_pan", "Req 3 Protect stored data",
           "Is stored cardholder data (PAN) rendered unreadable "
           "(encryption / truncation / tokenization)?",
           "no", "high", "Encrypt or tokenize stored PAN; never store sensitive "
           "authentication data (Req 3)."),
        _q("pci_transit", "Req 4 Protect data in transit",
           "Is cardholder data encrypted with strong cryptography over open networks?",
           "no", "high", "Use TLS 1.2+ for cardholder data in transit (Req 4)."),
        _q("pci_malware", "Req 5 Malware protection",
           "Is anti-malware deployed and kept current on applicable CDE systems?",
           "no", "medium", "Deploy + update anti-malware on applicable systems (Req 5)."),
        _q("pci_secure_dev", "Req 6 Secure systems",
           "Are systems patched promptly and software developed securely?",
           "no", "high", "Patch promptly + follow a secure SDLC (Req 6)."),
        _q("pci_need_to_know", "Req 7 Restrict access",
           "Is access to cardholder data restricted by business need-to-know?",
           "no", "high", "Enforce least-privilege need-to-know access to CHD (Req 7)."),
        _q("pci_auth", "Req 8 Authenticate access",
           "Is MFA with unique IDs enforced for all access to the CDE?",
           "no", "high", "Require MFA + unique credentials for all CDE access (Req 8)."),
        _q("pci_logging", "Req 10 Log and monitor",
           "Is all access to cardholder data and CDE systems logged and reviewed?",
           "no", "high", "Log + review access to cardholder data (Req 10)."),
        _q("pci_testing", "Req 11 Test security",
           "Are vulnerability scans and penetration tests performed regularly?",
           "no", "medium", "Run quarterly ASV scans + annual penetration tests (Req 11)."),
    ),
)

TEMPLATES: dict[str, AssessmentTemplate] = {
    t.type: t for t in (
        _PIA, _AIRA, _VENDOR_RISK,
        _SOX_CONTROL, _FRAUD_RISK, _ITGC, _CREDIT_RISK, _CLOSE_READINESS,
        _HIPAA, _SOC2, _PCI_DSS,
    )
}


def list_templates() -> list[AssessmentTemplate]:
    return list(TEMPLATES.values())


def get_template(assessment_type: str) -> AssessmentTemplate | None:
    return TEMPLATES.get((assessment_type or "").strip().lower())


# --- A running assessment --------------------------------------------------

@dataclass
class AssessmentSession:
    """An in-progress assessment of ``subject`` against a template. Answers are
    recorded by id; :meth:`evaluate` scores them into findings + a risk rating."""

    type: str = ""
    subject: str = ""
    answers: dict[str, dict] = field(default_factory=dict)
    id: str = field(default_factory=_new_session_id)
    created_at: float = field(default_factory=time.time)

    def restart(self, assessment_type: str, subject: str) -> None:
        """Start a new assessment draft in this reusable conversation session."""
        self.type = assessment_type
        self.subject = subject
        self.answers.clear()
        self.id = _new_session_id()
        self.created_at = time.time()

    def template(self) -> AssessmentTemplate:
        tpl = get_template(self.type)
        if tpl is None:
            raise KeyError(f"unknown assessment type {self.type!r}")
        return tpl

    def record(self, question_id: str, answer: str, note: str = "") -> None:
        answer = (answer or "").strip().lower()
        if answer not in ANSWERS:
            raise ValueError(f"answer must be one of {ANSWERS}, got {answer!r}")
        if self.template().question(question_id) is None:
            raise KeyError(f"no question {question_id!r} in {self.type!r}")
        self.answers[question_id] = {"answer": answer, "note": note}

    def evaluate(self) -> AssessmentResult:
        tpl = self.template()
        findings: list[Finding] = []
        answered = 0
        for q in tpl.questions:
            rec = self.answers.get(q.id)
            if not rec:
                continue
            ans = rec["answer"]
            if ans in {"yes", "no", "na"}:
                answered += 1
            if ans == q.risk_answer:
                findings.append(Finding(
                    q.id, q.section, q.text, q.severity, ans, "risk", q.guidance,
                ))
            elif ans == "unknown":
                findings.append(Finding(
                    q.id, q.section, q.text, q.severity, ans, "unverified",
                    q.guidance,
                ))
        return AssessmentResult(
            type=self.type,
            subject=self.subject,
            risk_rating=_rollup([f.severity for f in findings]),
            findings=findings,
            answered=answered,
            total=len(tpl.questions),
        )


def _rollup(severities: list[str]) -> str:
    if not severities:
        return "minimal"
    top = max(_SEVERITY_RANK.get(s, 1) for s in severities)
    return {3: "high", 2: "medium", 1: "low"}[top]


# --- Persistence -----------------------------------------------------------

def _assessments_dir() -> Path:
    from .paths import data_dir
    return data_dir("assessments")


def save_session(session: AssessmentSession) -> Path:
    """Persist a session + its current evaluation as JSON. Returns the path."""
    d = _assessments_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    result = session.evaluate()
    path = d / f"{session.id}.json"
    payload = json.dumps({
        "id": session.id,
        "type": session.type,
        "subject": session.subject,
        "created_at": session.created_at,
        "answers": session.answers,
        "result": asdict(result),
    }, indent=2, default=str)
    # The assessment holds sensitive content (subject, answers, findings); write
    # it 0600 so a co-tenant on a shared host can't read it (like dsar export).
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    return path


def list_saved() -> list[dict]:
    """Summaries of saved assessments, newest first."""
    d = _assessments_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        res = data.get("result", {})
        out.append({
            "id": data.get("id", p.stem),
            "type": data.get("type", "?"),
            "subject": data.get("subject", "?"),
            "risk_rating": res.get("risk_rating", "?"),
            "findings": len(res.get("findings", [])),
            "created_at": data.get("created_at", 0),
        })
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


def load_saved(assessment_id: str) -> dict | None:
    base = _assessments_dir()
    path = (base / f"{assessment_id}.json").resolve()
    # Guard against path traversal: ``assessment_id`` is a server-generated id and
    # the file must sit directly in the assessments dir. A ``../`` id resolves
    # outside it and is refused (so `assess show ../../etc/passwd` can't read it).
    if path.parent != base.resolve():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- Rendering -------------------------------------------------------------

def render_questions_text(tpl: AssessmentTemplate) -> str:
    head = f"{tpl.title} ({tpl.framework}) -- {len(tpl.questions)} questions"
    lines = [head, "=" * len(head), ""]
    section = None
    for q in tpl.questions:
        if q.section != section:
            section = q.section
            lines.append(f"[{section}]")
        lines.append(f"  {q.id}  ({q.severity}; risk if {q.risk_answer})")
        lines.append(f"     {q.text}")
    return "\n".join(lines)


def render_questions_json(tpl: AssessmentTemplate) -> str:
    return json.dumps({
        "type": tpl.type, "title": tpl.title, "framework": tpl.framework,
        "questions": [asdict(q) for q in tpl.questions],
    }, indent=2)


def render_result_text(result: AssessmentResult) -> str:
    tpl = get_template(result.type)
    title = tpl.title if tpl else result.type
    head = f"{title}: {result.subject}"
    lines = [
        head, "=" * len(head), "",
        f"Risk rating: {result.risk_rating.upper()}",
        f"Completeness: {result.answered}/{result.total} answered, "
        f"{len(result.findings)} finding(s)",
        "",
    ]
    if not result.findings:
        lines.append("No findings recorded.")
    else:
        lines.append("Findings (highest severity first):")
        order = {"high": 0, "medium": 1, "low": 2}
        for f in sorted(result.findings, key=lambda f: order.get(f.severity, 3)):
            flag = "UNVERIFIED" if f.kind == "unverified" else f.severity.upper()
            lines.append(f"  [{flag}] {f.section}: {f.question}")
            lines.append(f"      -> {f.recommendation}")
    return "\n".join(lines)


def render_result_json(result: AssessmentResult) -> str:
    return json.dumps(asdict(result), indent=2, default=str)


# --- The conversational assessor agent -------------------------------------

ASSESSMENT_PERSONA = (
    "You are Maverick's compliance assessor. You conduct structured assessments "
    "(privacy impact, AI risk, vendor risk). First call list_assessments to see "
    "the types, then start_assessment with the type and the subject being "
    "assessed. Answer each question from the documents and facts you were given, "
    "one at a time, with answer_question -- yes/no/na, or 'unknown' when you "
    "genuinely cannot verify it from the evidence. NEVER guess: 'unknown' is the "
    "honest answer when the evidence is silent. When every question is answered, "
    "call finalize_assessment to produce the scored findings. You produce a DRAFT "
    "for a human reviewer (DPO / risk owner) to sign off; you never approve it "
    "yourself."
)


def build_assessment_agent(ctx, session: AssessmentSession | None = None):
    """Construct the compliance-assessor agent: an Agent with the assessor persona
    and the assessment tools bound to a shared :class:`AssessmentSession`. Returns
    ``(agent, session)``. Mirrors :func:`maverick.intake.build_intake_agent` -- the
    live chat loop reuses the normal agent surface; this assembles the assessor."""
    from .agent import Agent
    from .tools import ToolRegistry
    from .tools.assessment_tools import assessment_tools

    session = session or AssessmentSession()
    agent = Agent(
        ctx=ctx, role="assessment",
        brief="Conduct a compliance assessment and produce scored findings.",
        persona=ASSESSMENT_PERSONA,
    )
    # The assessor only needs its own tools; replace the full base registry
    # (shell, filesystem, MCP, ...) with an assessment-only one.
    agent.tools = ToolRegistry()
    for tool in assessment_tools(session):
        agent.tools.register(tool)
    return agent, session


# --- The first-round privacy analyst ---------------------------------------

PRIVACY_ANALYST_PERSONA = (
    "You are Maverick's privacy & security analyst -- the first-round analyst. "
    "Given a subject (a vendor, an AI system, or a processing activity) you "
    "conduct the assessment end to end:\n"
    "1. RESEARCH the subject from the documents/context you are given (read_file, "
    "knowledge_search) and the web (web_search), gathering the evidence each "
    "question needs.\n"
    "2. start_assessment for the right framework (call list_assessments for the set "
    "-- privacy: vendor_risk/aira/pia; security: hipaa/soc2/pci_dss), then answer "
    "each question from that evidence with answer_question -- yes/no/na, or "
    "'unknown' when the evidence is genuinely silent. NEVER guess.\n"
    "3. For each risk, call find_controls to cite the specific control and framework "
    "reference (GDPR / EU AI Act / ISO 27001 / SOC 2 / NIST / HIPAA) that closes it.\n"
    "4. finalize_assessment to produce the scored findings.\n"
    "You produce a DRAFT with cited controls for a human reviewer (DPO / risk owner) "
    "to sign off. You never approve or certify compliance yourself."
)

# The analyst's safe envelope: read-only research + the control catalog. Mutating
# tools (shell, write_file, ...) are excluded -- and so is ``http_fetch``: it can
# POST an arbitrary body to any URL, which a prompt-injected analyst (it ingests
# untrusted subject material) could use to exfiltrate what it read. ``web_search``
# stays as the research channel (a query, not an arbitrary request body).
_ANALYST_RESEARCH_TOOLS = (
    "read_file", "web_search", "knowledge_search", "find_controls",
)


def _privacy_analyst_tools(base_registry, session: AssessmentSession):
    """Curate the analyst's registry: keep the read-only research + control tools
    from ``base_registry`` and add the assessment tools bound to ``session``."""
    from .tools import ToolRegistry
    from .tools.assessment_tools import assessment_tools

    reg = ToolRegistry()
    for name in _ANALYST_RESEARCH_TOOLS:
        try:
            reg.register(base_registry.get(name))
        except KeyError:
            continue  # tool not present in this build (e.g. web_search disabled)
    for tool in assessment_tools(session):
        reg.register(tool)
    return reg


def build_privacy_analyst_agent(ctx, session: AssessmentSession | None = None):
    """Construct the first-round privacy analyst: an Agent that researches a subject
    (read-only research tools), conducts the structured assessment, and cites the
    control for each finding. Returns ``(agent, session)``. The agent's registry is
    curated to the read-only research/control tools plus the assessment tools, so it
    can gather evidence and score it but cannot take mutating/outward actions."""
    from .agent import Agent

    session = session or AssessmentSession()
    agent = Agent(
        ctx=ctx, role="privacy_analyst",
        brief="Research the subject and conduct a scored compliance assessment.",
        persona=PRIVACY_ANALYST_PERSONA,
    )
    agent.tools = _privacy_analyst_tools(agent.tools, session)
    return agent, session


COMPLIANCE_AUDITOR_PERSONA = (
    "You are Maverick's compliance auditor. Given a framework (hipaa / soc2 / "
    "pci_dss, or another from list_assessments) and a subject -- usually THIS "
    "deployment, sometimes a vendor -- you produce an audit-readiness report a "
    "human compliance officer signs off.\n"
    "1. list_assessments, then start_assessment for the framework.\n"
    "2. Gather EVIDENCE before answering: deployment_posture for this system's live "
    "control state, read_file / knowledge_search for policies and documents, "
    "web_search for the framework's requirements. Answer each control with "
    "answer_question -- yes/na when the evidence shows it is met, no when it is not, "
    "'unknown' when there is NO evidence (an honest gap, never a guessed pass).\n"
    "3. For each gap, find_controls to cite the control and its remediation.\n"
    "4. finalize_assessment for the scored gaps, then frame it as audit readiness: "
    "what is in place, what is missing (ranked by severity), and the remediation "
    "roadmap. You DRAFT the readiness report -- the compliance officer signs off. "
    "You never declare the system 'compliant', 'certified', or 'audit-passed'."
)


def _compliance_auditor_tools(base_registry, session: AssessmentSession):
    """The auditor's envelope: the analyst's read-only research + control +
    assessment tools, plus ``deployment_posture`` for live control-state evidence."""
    from .tools.posture_tools import posture_tools

    reg = _privacy_analyst_tools(base_registry, session)
    for tool in posture_tools():
        reg.register(tool)
    return reg


def build_compliance_auditor_agent(ctx, session: AssessmentSession | None = None):
    """Construct the compliance auditor: an Agent that audits a subject (usually this
    deployment) against a framework -- gathering evidence from the live control
    posture + documents, scoring the gaps, and drafting an audit-readiness report
    for a human to sign off. Returns ``(agent, session)``. Read-only research +
    control + assessment tools plus deployment_posture; no mutating/outward tools."""
    from .agent import Agent

    session = session or AssessmentSession()
    agent = Agent(
        ctx=ctx, role="compliance_auditor",
        brief="Audit the subject against a framework and draft an audit-readiness "
              "report for a human to sign off.",
        persona=COMPLIANCE_AUDITOR_PERSONA,
    )
    agent.tools = _compliance_auditor_tools(agent.tools, session)
    return agent, session


__all__ = [
    "COMPLIANCE_AUDITOR_PERSONA",
    "build_compliance_auditor_agent",
    "ANSWERS",
    "ASSESSMENT_PERSONA",
    "build_assessment_agent",
    "PRIVACY_ANALYST_PERSONA",
    "build_privacy_analyst_agent",
    "Question",
    "AssessmentTemplate",
    "Finding",
    "AssessmentResult",
    "AssessmentSession",
    "TEMPLATES",
    "list_templates",
    "get_template",
    "save_session",
    "list_saved",
    "load_saved",
    "render_questions_text",
    "render_questions_json",
    "render_result_text",
    "render_result_json",
]
