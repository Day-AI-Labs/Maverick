# Incident Response Runbook

| Field | Value |
| --- | --- |
| Document ID | PROC-01 |
| Owner | Security Lead / Incident Commander |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual + after every SEV1/SEV2 |
| Frameworks | SOC 2 CC7.3, CC7.4; ISO/IEC 27001:2022 A.5.24, A.5.25, A.5.26, A.5.27, A.5.28; ISO/IEC 42001:2023 A.10 (AI incidents) |

This runbook operationalizes the Incident Response Policy (POL-07). Use the
incident report template (TPL-01) for every declared incident. Paths below are
relative to `packages/maverick-core/` unless absolute.

---

## 1. Purpose & scope

**Purpose.** Provide on-call responders with concrete, ready-to-run procedures
to detect, classify, contain, eradicate, recover from, and review incidents
affecting Maverick.

**Scope — covers both:**

- **Security incidents** — confidentiality / integrity / availability events:
  data breach or exfiltration, credential or key compromise, unauthorized
  access, malware, denial of service, externally reported vulnerabilities.
- **AI / agent incidents** (ISO 42001 A.10) — a model or agent behaving
  unsafely, exceeding authorized scope, taking an unsafe autonomous action,
  prompt-injection compromise, a governance/guardrail bypass, a fairness
  alert, or runaway/uncontrolled learning.

**Out of scope:** routine bugs with no safety/security/data impact (handle via
normal engineering triage); provider control-plane outages (coordinate here,
but provider response is an inherited control).

---

## 2. Severity classification matrix

Classify at triage; re-classify as facts change (always escalate on doubt).
Response-time targets are measured from declaration.

| Sev | Definition | Examples | Ack / response target | Who is paged |
| --- | --- | --- | --- | --- |
| **SEV1 — Critical** | Confirmed or highly likely breach, irreversible data loss, or an unsafe autonomous action with real-world impact. Active, spreading, or customer-facing harm. | Confirmed PII/customer-data exfiltration; audit-signing key compromise; an agent executed a destructive/irreversible real-world action; prompt-injection that bypassed the shield and reached a high-privilege tool; ransomware. | Ack **15 min**, IC engaged **30 min**, containment underway **1 h** | IC + Security Lead + Comms Lead + Eng on-call + Management. Page immediately. |
| **SEV2 — High** | Serious incident, contained or containable, with significant but bounded impact; or a near-miss that only governance/killswitch stopped. | Killswitch fired on an agent attempting an out-of-scope action; single-tenant data exposure; repeated `shield_block` / `governance_denied` indicating an active attack; capability misconfiguration granting excess privilege; confirmed exploitable vuln in production. | Ack **30 min**, IC engaged **1 h**, containment **4 h** | IC + Security Lead + Eng on-call. Comms Lead + Management notified (not necessarily paged). |
| **SEV3 — Medium** | Limited-impact incident, no confirmed data exposure, system functioning within guardrails. | Single fairness alert needing review; circuit breaker repeatedly tripping on a non-critical dependency; isolated capability-denied anomaly; low-severity reported vuln. | Ack **4 h** (business hours), resolve **3 business days** | Security Lead + owning Eng team. |
| **SEV4 — Low** | Minor / informational; policy or hygiene issue, no operational impact. | Single anomalous audit event explained on review; cosmetic guardrail false positive; low-risk dependency advisory. | Ack **1 business day**, resolve **10 business days** | Owning team via ticket. No page. |

**Auto-escalation triggers (treat as ≥ SEV2 until disproved):** any HALT fired
in production; any `verify_chain` / `verify_anchors` failure (possible audit
tampering); any confirmed access to customer data by an unauthorized party;
any agent action outside its approved capability set.

---

## 3. Roles & responsibilities

Roles are assigned at declaration. One person may hold two roles in SEV3/SEV4;
SEV1/SEV2 require distinct IC and Scribe at minimum.

| Role | Responsibilities |
| --- | --- |
| **Incident Commander (IC)** | Owns the incident end to end. Declares severity, runs the bridge, assigns roles, decides on containment actions (including authorizing HALT), tracks the timeline, declares resolution. Single decision-maker — does not do hands-on remediation. |
| **Security Lead** | Technical lead for investigation, forensics, and containment. Pulls and verifies audit evidence, executes/oversees killswitch, circuit-breaker, and capability-revocation actions, drives root-cause analysis. |
| **Comms Lead** | Owns all communication: internal status updates (cadence below), and **[Org action]** drafting customer / regulator notifications for legal & management sign-off. Single source of external truth — no one else communicates externally. |
| **Scribe** | Maintains the contemporaneous timeline in the TPL-01 report: every action, decision, time (UTC), and who did it. Captures evidence references (audit day-files, event kinds, command output). Keeps the report current in real time. |

**Status update cadence:** SEV1 every 30 min; SEV2 every 2 h; SEV3 daily.

---

## 4. Lifecycle phase checklists

### Phase 1 — Detect

- [ ] Capture the trigger: alert, killswitch/HALT event, `shield_block` spike,
      `fairness_alert`, customer report, or `SECURITY.md` vulnerability report.
- [ ] Record first-detected timestamp (UTC) and source in TPL-01.
- [ ] Preserve volatile evidence **before** changing anything (note current
      audit day-file, snapshot relevant logs).
- [ ] Declare an incident and assign IC. Do not investigate informally.

### Phase 2 — Triage / Assess

- [ ] IC assigns Security Lead, Comms Lead, Scribe; opens the bridge.
- [ ] Assign provisional severity from the §2 matrix (escalate on doubt).
- [ ] Determine type: security, AI/agent, or both → pick the §7 playbook.
- [ ] Scope it: which agents, tenants, capabilities, data subjects, systems.
- [ ] Decide whether immediate containment (HALT) is needed **now** — if a SEV1
      autonomous-action or active-exfiltration is plausible, HALT first, ask later.

### Phase 3 — Contain (see §5 for exact commands)

- [ ] Stop the harm: HALT the affected agent/cluster, trip circuit breakers,
      and/or revoke the offending capability.
- [ ] Isolate compromised credentials/keys; rotate as needed.
- [ ] Confirm containment held (re-check killswitch state; watch audit stream).
- [ ] Record every containment action + timestamp in TPL-01.

### Phase 4 — Eradicate

- [ ] Identify and remove root cause (bad config, vuln, poisoned learning
      state, malicious input pattern).
- [ ] For AI incidents: roll back the learned state to a known-good snapshot
      (§7) before re-enabling learning.
- [ ] Patch/deploy fix; add a guardrail or shield rule if the attack bypassed
      existing controls.
- [ ] Re-run `verify_chain` / `verify_anchors` to confirm the audit log is intact.

### Phase 5 — Recover

- [ ] Restore service in a controlled, observable way (canary/single tenant first).
- [ ] Clear the killswitch only when IC authorizes (file + in-process + shared,
      §5). Confirm no HALT remains active.
- [ ] Reset tripped circuit breakers; re-grant capabilities deliberately.
- [ ] Monitor for recurrence for a defined watch period before declaring
      resolution. IC declares resolved; record resolution timestamp.

### Phase 6 — Post-incident review

- [ ] See §9. Schedule within 5 business days; blameless.

---

## 5. Technical containment controls (exist in Maverick)

All operator actions below are **[Org action]** in that a human must authorize
them, but the mechanism is pre-built. Commands assume a shell on a host with
the Maverick environment and `MAVERICK_DATA_DIR` / `MAVERICK_HALT_FILE` set as
in production.

### 5.1 Killswitch — global halt

Implementation: `maverick/killswitch.py`. The halt is checked at tool-call
boundaries via `killswitch.check()` (raises `Halted`), so a halt stops agents
at the next tool invocation. Three independent triggers:

1. **File trigger (fastest, no Python needed):** create the HALT file. Default
   path is `~/.maverick/HALT` (i.e. `<data_dir>/HALT`); override via the
   `MAVERICK_HALT_FILE` env var.

   ```bash
   # Halt this host immediately
   touch "${MAVERICK_HALT_FILE:-$HOME/.maverick/HALT}"
   ```

   Polled cheaply (throttled ~1/s) at every tool boundary.

2. **In-process trigger (records a reason + audit event):**

   ```python
   from maverick import killswitch
   killswitch.halt("SEV1: unsafe autonomous action by agent X", source="manual")
   # records EventKind.HALT to the audit log
   ```

3. **Cluster-wide trigger (all hosts sharing the world DB):** when a Postgres
   world store is configured, arm the shared halt so every host stops, not just
   the local one. Consulted via the shared world store (`world.active_halt()`,
   throttled, fail-open):

   ```python
   from maverick.world_model import open_world
   w = open_world()
   w.arm_halt(reason="SEV1: cluster-wide halt", source="incident-PROC-01")
   ```

**Verify the halt took effect:**

```python
from maverick import killswitch
killswitch.is_active()   # True when any trigger is live
killswitch.check()       # raises Halted(...) if halted
```

**Clearing (Recovery only, IC-authorized — clear ALL three):**

```bash
rm -f "${MAVERICK_HALT_FILE:-$HOME/.maverick/HALT}"        # 1. file
```
```python
from maverick import killswitch
killswitch.clear()                                          # 2. in-process
from maverick.world_model import open_world
open_world().disarm_halt()                                  # 3. cluster (if armed)
```

> Note: `killswitch.clear()` resets only the in-process halt; it does **not**
> delete the HALT file. You must remove the file and disarm the shared halt
> separately or the system will re-halt.

### 5.2 Circuit breakers

Implementation: `maverick/circuit_breaker.py`. Classic three-state breaker
(CLOSED → OPEN → HALF_OPEN), thread-safe, used to fail fast on a misbehaving
dependency or tool. Operator actions:

```python
from maverick import circuit_breaker
circuit_breaker.snapshot()     # list all breakers + state/stats — triage view
cb = circuit_breaker.get("name-of-breaker")
cb.state                       # CircuitState: closed/open/half_open
cb.reset()                     # force CLOSED (Recovery)
circuit_breaker.reset_all()    # reset every breaker (use with care)
```

To force-isolate a failing dependency during containment, leave its breaker
OPEN (do not reset) until the dependency is confirmed healthy.

### 5.3 Capability revocation

Revoke the specific capability the agent abused rather than halting everything
when the blast radius is one capability. Confirm revocation took effect by
watching for `capability_denied` audit events on the next attempt (§6). Record
the capability, principal, and channel revoked in TPL-01.

---

## 6. Evidence collection (forensic record)

The **tamper-evident signed audit log** is the system of record for forensics.
Do not reconstruct events from memory when the audit log can prove them.

- **Location:** `maverick/audit/` — append-only, hash-chained, Ed25519-signed
  day-files (one file per UTC day) plus periodic anchors.
- **Chain verification:** `maverick/audit/signing.py`
  - `verify_chain(path)` — walks a single day-file, confirms every signature
    and the hash chain; returns a list of `ChainBreak` (empty = intact).
  - `verify_anchors(audit_dir)` — confirms day-file tips against the anchor
    ledger (detects deletion/replacement of whole day-files).

  ```python
  from pathlib import Path
  from maverick.audit import signing, reader
  audit_dir = reader.resolve_audit_dir(None)     # resolves the live audit dir (tenant=None)
  for day in signing.day_files(audit_dir):
      breaks = signing.verify_chain(day)
      if breaks:
          print("CHAIN BREAK", day, breaks)      # evidence of tampering — escalate
  print("anchors:", signing.verify_anchors(audit_dir))
  ```

  Any non-empty result from `verify_chain` / `verify_anchors` is itself an
  auto-escalation trigger (possible tampering) — preserve the file, snapshot
  the host, and treat as ≥ SEV2.

- **Relevant audit event kinds to pull** (`maverick/audit/events.py`):

  | Event kind | Pull it for |
  | --- | --- |
  | `shield_block` | Input/tool/output blocked by the shield (stage, reason, score) — prompt-injection, exfil attempts. |
  | `capability_denied` | Agent tried to use a capability it lacked (tool, principal, channel). |
  | `consent_result` | Human approve/deny/timeout on a gated action. |
  | `governance_denied` | Governance/policy guardrail blocked an action. |
  | `fairness_alert` | Fairness/bias threshold breached. |
  | `ai_system_retired` | An AI system/agent was retired/decommissioned. |
  | `halt` | Killswitch fired (source, reason). |

- **Preserve, don't alter.** Copy the relevant day-file(s) to evidence storage;
  never edit in place. Record the exact day-file names and event kinds pulled
  in the TPL-01 "evidence references" section. The audit log is append-only —
  the act of collecting evidence must not write to it.

---

## 7. AI-incident playbook (ISO 42001 A.10)

General pattern for any AI/agent-safety incident: **Halt → Snapshot → Roll back
→ Review → Re-enable**. Pick the row matching the symptom.

| Symptom | Steps |
| --- | --- |
| **Agent behaving unsafely / out of scope / unsafe autonomous action** | 1. **HALT** the agent (§5.1) — file trigger first for speed, then in-process for the audit reason; cluster-wide if multi-host. 2. Pull `governance_denied`, `capability_denied`, `consent_result`, `halt` events (§6) to reconstruct what it attempted. 3. If it abused one capability, **revoke that capability** (§5.3) and keep others up; otherwise leave halted. 4. Determine reversibility of any action taken; engage owners to undo real-world effects. **[Org action]** 5. Eradicate root cause; re-enable only after IC sign-off. |
| **Prompt-injection compromise** | 1. HALT if a high-privilege tool was reached; else trip the relevant capability. 2. Pull `shield_block` events (stage = input/tool/output) to see what the shield caught vs. missed. 3. Capture the malicious input as evidence; add a shield/guardrail rule to block the pattern (eradication). 4. Verify no learned state was poisoned (§ runaway-learning row). 5. Re-enable after the new rule is confirmed effective. |
| **Fairness alert** | 1. Triage severity from §2 (usually SEV3 unless customer-impacting). 2. Pull `fairness_alert` events for the metric, threshold, and affected cohort. 3. If actively producing biased outputs at scale, HALT or revoke the capability; otherwise pause the affected workflow. 4. Root-cause (data, prompt, learned drift); fix and document. 5. **[Org action]** assess any required customer/regulator disclosure (§8). |
| **Runaway / uncontrolled learning** | 1. HALT learning-driven agents. 2. **Snapshot** current learned state for evidence: `from maverick import dreaming; dreaming.snapshot_learning_state()`. 3. **Roll back** to the last known-good snapshot: `dreaming.rollback_learning_state("latest")` (whole-store rollback). 4. Promotions go through the staged rollout (`maverick/learning_rollout.py`) whose `promote_skill_live` snapshots first and auto-rolls-back on any failed constraint — confirm the failed rollout rolled back, and re-run with tightened constraints. 5. Record the signed learning-audit row; verify the audit chain (§6) before re-enabling learning. |

In all AI-incident cases, an `ai_system_retired` event should be recorded if an
agent/model is permanently decommissioned as the resolution.

---

## 8. External communication & breach notification

**[Org action] for all external comms.** Only the Comms Lead communicates
externally, and only after legal & management sign-off. Use the decision tree,
then the timelines.

### Notification decision tree

```
Is the incident a confirmed/likely PERSONAL DATA breach?
├── No  → No GDPR obligation. Still: notify customers if a DPA/SLA term is
│         triggered (see below). Coordinate any vuln disclosure per SECURITY.md.
└── Yes → Does it risk the rights/freedoms of data subjects?
          ├── Unlikely (e.g. data was encrypted/unintelligible)
          │     → Document the assessment & reasoning; no Art.33 notice required,
          │       but RECORD the decision. Re-evaluate as facts develop.
          └── Likely
                ├── GDPR Art. 33: notify the supervisory authority WITHOUT UNDUE
                │   DELAY and where feasible within **72 hours** of becoming aware.
                │   If > 72h, include reasons for the delay.   [Org action]
                └── HIGH risk to data subjects?
                      ├── Yes → GDPR Art. 34: notify affected DATA SUBJECTS without
                      │         undue delay, in clear plain language.   [Org action]
                      └── No  → Art. 34 not required; document why.
```

### Timelines & obligations checklist

- [ ] **GDPR Art. 33 — supervisory authority:** within **72 hours** of awareness
      when a personal-data breach is likely to risk individuals' rights.
      **[Org action]** Comms Lead drafts; legal approves; DPO/management submits.
- [ ] **GDPR Art. 34 — data subjects:** without undue delay when there is a
      **high** risk to individuals. **[Org action]** legal-approved wording.
- [ ] **Customer notification per DPA:** notify affected customers within the
      window in their Data Processing Agreement / contract (often 24–72 h).
      **[Org action]** Comms Lead checks each affected customer's DPA term.
- [ ] **Vulnerability disclosure:** for externally reported vulns, coordinate via
      `SECURITY.md` — the Organization follows a **90-day coordinated
      disclosure window** from initial report; public advisory/CVE only after a
      patched release. Keep the reporter updated. **[Org action]**
- [ ] Record every notification made (who, when, channel) in TPL-01.

---

## 9. Post-incident review (PIR)

- **When:** within **5 business days** of resolution. Mandatory for SEV1/SEV2;
  recommended for SEV3.
- **How:** **blameless** — focus on systems and process, not individuals.
- **Inputs:** the completed TPL-01 report, the contemporaneous timeline, and the
  verified audit evidence.
- **Agenda checklist:**
  - [ ] Confirm timeline (detection → resolution) is complete and accurate.
  - [ ] Identify root cause(s) and contributing factors.
  - [ ] What detected it? What delayed detection/containment? What went well?
  - [ ] Did containment controls (killswitch, breakers, capability revocation,
        shield/governance) work as intended? Any gaps?
  - [ ] Was the audit evidence sufficient and intact (`verify_chain`/`verify_anchors`)?
- **Outputs (with owners + due dates):**
  - [ ] Corrective actions logged in the **corrective-action log**.
  - [ ] New/updated risks recorded in the **risk register**.
  - [ ] Runbook/guardrail/control improvements filed.
  - [ ] Trigger an out-of-cycle review of this runbook (review cycle = annual +
        after every SEV1/SEV2).
