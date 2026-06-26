# Incident Response Policy

| Field | Value |
| --- | --- |
| Document ID | POL-07 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.5.24, A.5.25, A.5.26, A.5.27, A.5.28, A.6.8; ISO/IEC 42001:2023 A.10.x; SOC 2 CC7.3, CC7.4 |

## 1. Purpose

This policy establishes how the Organization detects, reports, classifies, responds to, contains, eradicates, and recovers from information security and AI incidents affecting Maverick, and how it learns from them. It defines the lifecycle from event detection through post-incident review and external/customer notification, so that incidents are handled consistently, evidence is preserved in a tamper-evident manner, and obligations (including breach-notification commitments) are met.

The policy explicitly covers AI-specific incidents as required by ISO/IEC 42001:2023 — for example, a model or agent behaving unsafely, exceeding its authorized scope, a prompt-injection compromise, or a governance/guardrail bypass — in addition to conventional security events.

## 2. Scope

This policy applies to:

- The Maverick platform (kernel `maverick-core`, shield, channels, dashboard, MCP, evolve, knowledge) and all production deployments operated by or on behalf of the Organization.
- All personnel, contractors, and on-call responders involved in detecting, reporting, or responding to incidents.
- All categories of incident: confidentiality/integrity/availability events, AI/agent safety and governance incidents, and externally reported vulnerabilities.
- The audit, telemetry, and containment subsystems used to detect and evidence incidents.

Infrastructure- and hosting-provider incident handling (e.g. cloud control-plane outages) is coordinated through this policy but the underlying provider response is an inherited control. **[Process — Organization to operationalize]**

## 3. Policy statements

1. **Detection.** Maverick shall continuously emit security- and governance-relevant events (shield blocks, consent decisions, capability denials) and integrity signals (audit-chain verification) that can surface anomalous or unsafe behavior. Monitoring of these signals and alert routing is an Organization process. **[Process — Organization to operationalize]**
2. **Reporting.** Any person who observes a suspected security or AI incident shall report it without delay through the designated reporting channel. Externally reported vulnerabilities follow the coordinated disclosure process in `SECURITY.md` (90-day coordinated disclosure window, defined reward tiers).
3. **Triage & classification.** Every reported event shall be assessed and classified by severity and type (security vs. AI-safety vs. availability), and a decision recorded on whether it constitutes an incident. Classification criteria, severity tiers, and ownership assignment are an Organization process. **[Process — Organization to operationalize]**
4. **Containment.** Confirmed incidents shall be contained using Maverick's halt and isolation primitives — the global killswitch and per-capability circuit breakers — to stop unsafe agent action at tool boundaries before eradication begins.
5. **AI-incident handling.** Where an incident involves a model or agent acting unsafely, an apparent prompt-injection compromise, or a guardrail/governance bypass, responders shall immediately invoke containment (halt and/or relevant circuit breakers), preserve the governance event trail, and classify the AI impact in line with ISO/IEC 42001 incident-reporting expectations.
6. **Eradication & recovery.** Root cause shall be removed and affected components restored to a known-good state before normal operation resumes. Recovery is coordinated with the Business Continuity Policy (POL-08).
7. **Evidence preservation.** The tamper-evident audit log shall be preserved as the primary forensic evidence for every incident; chain and anchor integrity shall be verified, and evidence handled to maintain its admissibility and integrity.
8. **Post-incident review.** Every significant incident shall undergo a documented review to capture root cause, response effectiveness, and corrective/preventive actions, feeding lessons back into controls and runbooks.
9. **External & customer notification.** Where an incident triggers contractual, regulatory, or breach-notification obligations, affected customers and authorities shall be notified within the applicable SLAs. The notification matrix, SLAs, and templates are an Organization process. **[Process — Organization to operationalize]**
10. **Program operationalization.** The technical halt/containment and evidence primitives are provided by Maverick; the surrounding IR program — on-call rotation, escalation paths, runbooks, and notification SLAs — shall be established and maintained by the Organization. **[Process — Organization to operationalize]**

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Incident Response Manager (Owner) | Owns this policy and the IR program; declares incidents, coordinates response, authorizes containment and recovery. **[Process — Organization to operationalize]** |
| On-call responder | First-line triage, classification, and execution of containment using killswitch/circuit breakers. **[Process — Organization to operationalize]** |
| Security Lead | Oversees vulnerability disclosure intake (`SECURITY.md`), evidence integrity, and forensic handling. |
| AI Safety / Governance owner | Assesses AI-specific incidents (unsafe agent behavior, prompt-injection, guardrail bypass) and ISO 42001 impact. **[Process — Organization to operationalize]** |
| Management (Approver) | Approves this policy; authorizes external/customer/regulator notification. |
| All personnel | Promptly report suspected security or AI incidents. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Global halt / emergency containment | `maverick/killswitch.py` — file trigger `~/.maverick/HALT`, in-process and cluster-wide via shared world DB, checked at tool boundaries | Implemented |
| Per-capability containment / isolation | `maverick/circuit_breaker.py` — circuit breakers trip failing capabilities/tools | Implemented |
| Incident / issue reporting intake | `maverick/issue_report.py` | Implemented |
| Detection signals (governance events) | `maverick/audit/events.py` — `shield_block`, `consent`, `capability_denied` events | Implemented |
| Forensic evidence store | `maverick/audit/` audit log (writer/reader) as forensic record of events | Implemented |
| Evidence integrity / tamper detection | `maverick/audit/signing.py` — `verify_chain` / `verify_anchors` | Implemented |
| Coordinated vulnerability disclosure | `SECURITY.md` — 90-day coordinated disclosure, reward tiers | Implemented |
| Detection monitoring & alert routing | Consumes events above | **[Process — Organization to operationalize]** |
| On-call, escalation, runbooks, notification SLAs | IR program around the primitives above | **[Process — Organization to operationalize]** |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.5.24 (IR planning & preparation), A.5.25 (assessment & decision on events), A.5.26 (response to incidents), A.5.27 (learning from incidents), A.5.28 (collection of evidence), A.6.8 (reporting information security events) |
| ISO/IEC 42001:2023 | A.10.x (AI incident reporting and impact assessment) |
| SOC 2 | CC7.3 (evaluate security events to determine response), CC7.4 (respond to identified security incidents) |

## 7. Exceptions & non-compliance

Exceptions to this policy require documented risk acceptance and approval by Management, with a defined expiry and compensating controls. Non-compliance — including failure to report a known incident, bypassing containment controls, or tampering with the audit/evidence trail — may result in disciplinary action and is itself a reportable security event. Process items marked **[Process — Organization to operationalize]** are tracked as open program gaps until formally established.

## 8. Review & maintenance

This policy is reviewed at least annually and upon significant change (e.g. material platform changes, a major incident, or audit findings). Review incorporates lessons learned from post-incident reviews. The Owner maintains the policy; Management approves material revisions. The version and effective date are updated on each approved change.
