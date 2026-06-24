# Risk Register

| Field | Value |
| --- | --- |
| Document ID | RM-REG-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — initial population, pending management review |
| Review cycle | Quarterly, and on significant change |
| Methodology | [`risk-management-methodology.md`](risk-management-methodology.md) |

This is the consolidated register of information-security and AI risks. It is
seeded from the STRIDE threat model (`docs/security/threat-model.md`), the
pen-test readiness scope (`docs/security/audit-readiness.md`), and the SOC 2
control gaps ([`soc2-controls.md`](soc2-controls.md)). Scores follow the
[methodology](risk-management-methodology.md): Likelihood × Impact, 1–25.

`I` = inherent (pre-control), `R` = residual (post-control). Controls are
cross-referenced to the [crosswalk](control-crosswalk.md) and SoA.

## Information-security risks

| ID | Risk | L×I (I) | Treatment / control | L×I (R) | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R-01 | **Sandbox escape** — agent-executed code breaks container isolation to reach the host | 4×5=20 | Mitigate: hardened container backends (`--network=none`, `--cap-drop=ALL`, `--no-new-privileges`, pid/mem limits); enterprise `require_container` deny-local (`maverick/sandbox/`) | 2×5=10 | Christopher Day | Treat — keep pen-test on roadmap |
| R-02 | **Prompt injection** redirects the agent to attacker goals | 5×4=20 | Mitigate: Agent Shield input/tool/output scanning; memory injection-marker guard (`maverick-shield/`, `maverick/memory_guard.py`) | 3×3=9 | Christopher Day | Treat — tune red-team corpus |
| R-03 | **Secret/credential exfiltration** via tool output or logs | 4×5=20 | Mitigate: secret scrubber + PII detector + exfil detection; detect-secrets CI gate (`maverick/secrets.py`, `maverick/safety/`) | 2×4=8 | Christopher Day | Treat |
| R-04 | **SSRF** to internal/cloud-metadata endpoints | 3×4=12 | Mitigate: DNS-rebind pinning, private-IP block (default-on) | 2×3=6 | Christopher Day | Treat |
| R-05 | **Audit-log tampering** hides malicious activity | 3×5=15 | Mitigate: Ed25519 Merkle hash-chain + cross-file anchors + WORM; chain verification (`maverick/audit/signing.py`) | 1×5=5 | Christopher Day | Treat — requires signing ENABLED |
| R-06 | **Unauthorized access** to dashboard / API | 4×4=16 | Mitigate: OIDC/SAML auth, RBAC, capabilities — **must be enabled** (`auth.py`, `rbac.py`, `capability.py`) | 2×4=8 | Christopher Day | Treat — opt-in controls must be on |
| R-07 | **Data at rest disclosure** (world DB / memory theft) | 3×4=12 | Mitigate: AES-256-GCM at-rest encryption; tenant isolation (`crypto_at_rest.py`, `paths.py`) | 2×3=6 | Christopher Day | Treat — encryption must be on |
| R-08 | **MCP / plugin supply-chain compromise** | 3×5=15 | Mitigate: command hash-pinning, tool-desc scan, plugin allowlist + hash-pin (`plugin_manifest.py`, `mcp_oauth.py`) | 2×4=8 | Christopher Day | Treat |
| R-09 | **Webhook spoofing** triggers unauthorized actions | 3×3=9 | Mitigate: HMAC verification (fail-closed 401), atomic dedup, sender allowlist | 1×3=3 | Christopher Day | Accept (low residual) |
| R-10 | **Dependency vulnerability** in third-party packages | 4×3=12 | Mitigate: Dependabot weekly; CI gates. **Process**: vuln-management cadence + pen test | 3×3=9 | Christopher Day | Treat — process gap open |
| R-11 | **Resource exhaustion / runaway spend** (DoS, cost) | 4×3=12 | Mitigate: hard Budget caps, per-principal quotas, concurrency + killswitch (`budget.py`, `quotas.py`) | 2×2=4 | Christopher Day | Accept |
| R-12 | **Availability loss / unrecoverable run** | 3×3=9 | Mitigate: durable checkpoint/resume, job queue, circuit breakers. **Process**: DR site, RTO/RPO | 2×3=6 | Christopher Day | Treat — process gap open |

## Process / organizational risks (shared compliance gaps)

| ID | Risk | L×I (I) | Treatment | L×I (R) | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R-13 | **No formal change-management process** (approvals, SoD, prod sign-off) | 3×4=12 | Establish process per POL-05; CI gates already enforce technical control | 2×3=6 | Christopher Day | **Open — Process** |
| R-14 | **No vendor/sub-processor management program** (LLM providers, infra) | 4×4=16 | Establish reviews + DPAs + maintained inventory per POL-09 | 2×3=6 | Christopher Day | **Open — Process** |
| R-15 | **No operational incident-response program** (on-call, escalation, breach SLAs) | 3×4=12 | Establish IR runbooks + on-call per POL-07; containment primitives exist | 2×3=6 | Christopher Day | **Open — Process** |
| R-16 | **No HR security controls** (screening, training, NDAs, offboarding) | 3×3=9 | Establish per POL-10 | 2×2=4 | Christopher Day | **Open — Process** |
| R-17 | **No documented, periodic risk-assessment program with management review** | 3×4=12 | This methodology + register + quarterly review closes it | 2×2=4 | Christopher Day | **In progress** |
| R-18 | **No scheduled vulnerability scanning / penetration testing cadence** | 4×4=16 | Establish quarterly scan + annual third-party pen test with remediation tracking | 2×3=6 | Christopher Day | **Open — Process** |

## AI-specific risks (ISO 42001)

| ID | Risk | L×I (I) | Treatment / control | L×I (R) | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R-19 | **Loss of human oversight** on consequential actions | 3×5=15 | Mitigate: governance ALLOW/DENY/REQUIRE_HUMAN; consent fail-closed; two-person approval (`governance.py`, `consent.py`) | 1×5=5 | Christopher Day | Treat — gates must be configured |
| R-20 | **Learning-loop regression / drift** degrades agent behavior | 3×4=12 | Mitigate: snapshot-replay regression detection, calibration gating, staged rollout, atomic rollback, signed learning audit | 2×3=6 | Christopher Day | Treat |
| R-21 | **Memory poisoning** via external agent contributions to fleet memory | 3×4=12 | Mitigate: provenance tagging, schema validation, secret redaction, Shield scan, write-path scope gating (`fleet_memory.py`) | 2×3=6 | Christopher Day | Treat |
| R-22 | **Bias / unfair outcomes** in agent decisions | 3×4=12 | Mitigate: on-demand group-fairness metrics (`tools/bias_eval.py`) **plus** continuous rolling-window monitoring with four-fifths/drift alerts to the signed audit log (`fairness_monitor.py`, `FAIRNESS_ALERT`) | 2×3=6 | Christopher Day | **Closed** |
| R-23 | **Missing transparency** to affected parties (undisclosed AI, no explanation) | 2×3=6 | Mitigate: Art.50 disclosure; right-to-explanation (`compliance.py`, `right_to_explanation.py`) | 1×3=3 | Christopher Day | Accept |
| R-24 | **No AI-system retirement/decommissioning procedure** | 2×3=6 | Mitigate: governed retirement with data disposition + signed `AI_SYSTEM_RETIRED` audit record; `erase` disposition wired to concrete subject-scoped deletion (audit `delete_user` + world `delete_facts_matching`) (`retirement.py`) | 1×3=3 | Christopher Day | **Closed** |
| R-25 | **No formal model-card metadata** (intended use, limits, eval results) | 2×3=6 | Mitigate: operator-declared metadata merged into model cards + export (`model_cards.py`) | 1×3=3 | Christopher Day | **Closed** |

## Heat summary (residual)

| Band | Count | IDs |
| --- | --- | --- |
| Critical (16–25) | 0 | — |
| High (10–15) | 1 | R-01 |
| Medium (5–9) | 15 | R-02–R-08, R-10, R-12–R-21 (subset) |
| Low (1–4) | 6 | R-09, R-11, R-16, R-17, R-23 (subset) |
| Closed | 3 | R-22, R-24, R-25 (controls now implemented) |

> R-01 (sandbox escape) remains the single High residual risk and is the
> headline target for the planned third-party penetration test. All Critical
> inherent risks are reduced to High or Medium by existing controls **once the
> opt-in security controls are enabled** — see [`soc2/README.md`](soc2/README.md).
