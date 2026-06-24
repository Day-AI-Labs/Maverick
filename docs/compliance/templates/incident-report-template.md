# Incident Report

| Field | Value |
| --- | --- |
| Document ID | TPL-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual + after every SEV1/SEV2 |
| Frameworks | SOC 2 CC7.3, CC7.4; ISO/IEC 27001:2022 A.5.24, A.5.25, A.5.26, A.5.27, A.5.28; ISO/IEC 42001:2023 A.10 (AI incidents) |

> Fill in one copy per declared incident. Keep it current **in real time**
> (the Scribe owns this during the incident). Times in **UTC, ISO 8601**.
> Cross-references: runbook PROC-01, policy POL-07.

---

## 1. Incident identification

| Field | Value |
| --- | --- |
| Incident ID | `INC-YYYY-NNNN` |
| Title (short) | _____ |
| Severity (SEV1–SEV4) | _____ (final) / _____ (initial, if re-classified) |
| Incident type | ☐ Security  ☐ AI/agent (ISO 42001 A.10)  ☐ Both  ☐ Reported vulnerability |
| Status | ☐ Open ☐ Contained ☐ Eradicated ☐ Recovered ☐ Resolved ☐ Closed |
| Incident Commander | _____ |
| Security Lead | _____ |
| Comms Lead | _____ |
| Scribe | _____ |
| Detection source | ☐ Alert ☐ HALT/killswitch ☐ Audit anomaly ☐ Customer report ☐ SECURITY.md vuln report ☐ Other: ___ |

---

## 2. Timeline (UTC)

| Timestamp (UTC) | Phase | Action / event | Actor |
| --- | --- | --- | --- |
| | Detect | First detected: ___ | |
| | Triage | Incident declared, severity ___ assigned | |
| | Contain | e.g. HALT fired / capability revoked / breaker left open | |
| | Eradicate | Root cause removed / patch deployed | |
| | Recover | Service restored / killswitch cleared | |
| | Resolve | IC declared resolved | |

Key durations: **Time to detect:** ___  **Time to contain:** ___
**Time to resolve:** ___

---

## 3. Affected assets, data & subjects

| Field | Value |
| --- | --- |
| Maverick components affected | ☐ kernel/core ☐ shield ☐ channels ☐ dashboard ☐ MCP ☐ evolve ☐ knowledge ☐ other: ___ |
| Agents / models involved | _____ |
| Tenants affected | _____ |
| Capabilities involved | _____ |
| Systems / hosts / infra | _____ |
| Data categories involved | ☐ None ☐ PII ☐ Customer data ☐ Credentials/keys ☐ Learned state ☐ Other: ___ |
| Personal data breach? | ☐ No ☐ Suspected ☐ Confirmed |
| Approx. number of data subjects affected | _____ |
| Cross-border / which jurisdictions | _____ |

---

## 4. Root cause

- **Immediate cause:** _____
- **Underlying / contributing factors:** _____
- **How control(s) were bypassed (if any)** (shield/governance/capability/budget): _____
- **For AI incidents** — model/agent behavior, prompt-injection vector, fairness
  metric breached, or learning-state issue: _____

---

## 5. Containment actions taken

| Time (UTC) | Action | Mechanism (PROC-01 §5) | Actor | Result |
| --- | --- | --- | --- | --- |
| | e.g. HALT file created | killswitch.py (file trigger) | | |
| | e.g. in-process halt + reason | killswitch.halt(...) | | |
| | e.g. cluster halt armed | world.arm_halt(...) | | |
| | e.g. capability revoked | capability revocation | | |
| | e.g. breaker left OPEN | circuit_breaker.py | | |
| | Killswitch cleared (recovery) | rm HALT + clear() + disarm_halt() | | |

---

## 6. Evidence references

> The signed audit log (`maverick/audit/`) is the forensic record. Reference,
> don't paraphrase.

| Field | Value |
| --- | --- |
| Audit day-file(s) preserved | e.g. `audit/2026-06-24.log` |
| Event kinds pulled | ☐ `shield_block` ☐ `capability_denied` ☐ `consent_result` ☐ `governance_denied` ☐ `fairness_alert` ☐ `ai_system_retired` ☐ `halt` |
| `verify_chain` result | ☐ Intact (no ChainBreak) ☐ Break detected: ___ |
| `verify_anchors` result | ☐ Intact ☐ Break detected: ___ |
| Other evidence (logs, snapshots, command output) | _____ |
| Evidence storage location | _____ |

---

## 7. Customer / regulator notifications made

| Notification | Required? | Done? | Date/time (UTC) | By whom | Reference |
| --- | --- | --- | --- | --- | --- |
| GDPR Art. 33 — supervisory authority (≤ 72 h) | ☐ Y ☐ N | ☐ | | | |
| GDPR Art. 34 — data subjects (high risk) | ☐ Y ☐ N | ☐ | | | |
| Customer notification per DPA | ☐ Y ☐ N | ☐ | | | |
| Vulnerability disclosure (SECURITY.md, 90-day) | ☐ Y ☐ N | ☐ | | | |

**[Org action]** All external notifications require legal & management sign-off
before sending. If a required notice was **not** sent, record the documented
rationale: _____

---

## 8. Corrective actions

| # | Corrective / preventive action | Owner | Due date | Status | Log/risk ref |
| --- | --- | --- | --- | --- | --- |
| 1 | | | | ☐ Open | corrective-action log #___ |
| 2 | | | | ☐ Open | risk register #___ |
| 3 | | | | ☐ Open | |

---

## 9. Lessons learned (blameless PIR)

- **What went well:** _____
- **What delayed detection / containment:** _____
- **Did containment controls work as intended (killswitch, breakers, capability
  revocation, shield/governance)?** _____
- **Was audit evidence sufficient and intact?** _____
- **Runbook / guardrail / control improvements identified:** _____

| PIR field | Value |
| --- | --- |
| PIR held on (≤ 5 business days after resolution) | _____ |
| Attendees | _____ |
| Report approved by (Management) | _____ |
| Date closed | _____ |
