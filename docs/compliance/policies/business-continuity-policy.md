# Business Continuity Policy

| Field | Value |
| --- | --- |
| Document ID | POL-08 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.5.29, A.5.30, A.8.13, A.8.14; SOC 2 A1.1, A1.2, A1.3 |

## 1. Purpose

This policy defines how the Organization maintains the availability and resilience of Maverick during disruption, and how it backs up, recovers, and tests the platform and its data. It covers availability, resilience, backup and recovery, ICT readiness for business continuity, capacity management, and recovery testing, so that Maverick can withstand and recover from disruptive events within acceptable limits.

## 2. Scope

This policy applies to:

- The Maverick platform (kernel `maverick-core`, shield, channels, dashboard, MCP, evolve, knowledge) and its production deployments.
- The mechanisms that provide durability, resilience, capacity control, and health observability within the platform.
- The personnel responsible for operating, recovering, and testing the platform.

Infrastructure- and disaster-recovery-site controls — data-center/hosting DR, backup of the deployment environment, RTO/RPO targets, and DR-site failover testing — are inherited from the cloud provider and operated as an Organization process. **[Process — Organization to operationalize]**

## 3. Policy statements

1. **Availability & resilience.** Maverick shall be designed and operated to degrade gracefully and remain available under partial failure, using durable state, concurrency control, and fault isolation so that disruptions are contained rather than cascading.
2. **Durable checkpoint & resume.** Long-running work shall be checkpointed durably so it can resume after interruption without loss of in-flight progress.
3. **Fault isolation.** Failing dependencies and capabilities shall be isolated via circuit breakers to prevent cascading failure and to preserve overall service availability.
4. **Capacity management.** Resource consumption shall be bounded by budgets, quotas, and concurrency limits to protect capacity and prevent resource-exhaustion outages.
5. **Health & monitoring.** Platform health shall be continuously observable so that degradation is detected and disruption response can begin promptly.
6. **Recovery testing.** Resilience and recovery behavior shall be exercised through fault-injection / chaos testing; the cadence, scope, and acceptance criteria of scheduled exercises are an Organization process. **[Process — Organization to operationalize]**
7. **Backup & recovery.** Information required to restore service shall be backed up and recoverable. Backup of the deployment environment, retention, and restore verification at the infrastructure layer are inherited from the hosting provider and operated by the Organization. **[Process — Organization to operationalize]**
8. **ICT readiness for continuity.** RTO/RPO targets, the continuity plan, and DR-site failover testing shall be defined, maintained, and exercised by the Organization. **[Process — Organization to operationalize]**

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Business Continuity Manager (Owner) | Owns this policy, the continuity plan, RTO/RPO targets, and recovery test schedule. **[Process — Organization to operationalize]** |
| Platform / SRE engineering | Operates checkpointing, job queue, circuit breakers, capacity controls, and health monitoring; executes recovery. |
| Resilience test owner | Plans and runs chaos/recovery exercises and records results. **[Process — Organization to operationalize]** |
| Cloud / Infrastructure provider | Provides inherited DR-site, environment backup, and infrastructure redundancy. **[Process — Organization to operationalize]** |
| Management (Approver) | Approves this policy and accepts residual continuity risk. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Durable checkpoint / resume | `maverick/checkpoint.py` | Implemented |
| Durable work queue / job recovery | `maverick/job_queue.py` | Implemented |
| Fault isolation / resilience | `maverick/circuit_breaker.py` | Implemented |
| Recovery & resilience testing | `maverick/chaos.py` (fault-injection / chaos testing) | Implemented |
| Concurrency limits | `maverick/net_concurrency.py` | Implemented |
| Capacity management / resource caps | `maverick/budget.py`, `maverick/quotas.py` | Implemented |
| Health checks / observability | `maverick/observability.py` | Implemented |
| Data-center / hosting DR, environment backup | Cloud provider (inherited) | **[Process — Organization to operationalize]** |
| RTO/RPO targets, DR-site failover testing | Continuity plan | **[Process — Organization to operationalize]** |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.5.29 (security during disruption), A.5.30 (ICT readiness for business continuity), A.8.13 (information backup), A.8.14 (redundancy) |
| SOC 2 | A1.1 (capacity demand managed), A1.2 (environmental protection, backup, recovery infrastructure), A1.3 (recovery plan testing) |

## 7. Exceptions & non-compliance

Exceptions to this policy require documented risk acceptance and approval by Management, with a defined expiry and compensating controls. Bypassing capacity, concurrency, or budget controls in production, or disabling resilience/health mechanisms without authorization, constitutes non-compliance and may result in disciplinary action. Process items marked **[Process — Organization to operationalize]** are tracked as open program gaps until formally established.

## 8. Review & maintenance

This policy is reviewed at least annually and upon significant change (e.g. material architecture changes, a major outage, or a failed recovery test). Recovery-test results and incident learnings (see POL-07) feed the review. The Owner maintains the policy; Management approves material revisions. The version and effective date are updated on each approved change.
