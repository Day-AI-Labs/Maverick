# Safety Steering Group — Charter

**Status:** Chartered (repo-side) · **Roadmap ref:** 2028-H1 Safety
"Safety steering group" · **Date:** June 2026

> **Honesty note.** This is the *charter* — the standing rules, scope, and
> decision process for a safety-governance body, plus the hooks that wire it
> to the controls already in the tree. **Staffing it** (naming members,
> convening it, holding it accountable) is a company act, not something a
> repository can do; the seats below are roles to fill, marked **TO STAFF**.
> The charter is written so that the day members are named, the body has a
> concrete remit and a paper trail to work from on day one.

## Purpose

The Safety Steering Group (SSG) is the body that owns Lightwork's safety
posture across releases: it decides what capabilities ship, under what
guardrails, and what gets declined — and it is the named escalation point
when a safety question can't be resolved inside a normal PR review. It exists
so that safety-significant decisions are made deliberately, by an accountable
group, with a written record — not implicitly, one merge at a time.

## Scope — what the SSG owns

1. **Capability gating.** Sign-off on any *dual-use* or
   safety-significant capability before it ships, default-ON or default-OFF.
   The decision is recorded as a decision doc under
   [`docs/specs/`](../specs/) (the established pattern — see
   [`anti-bot-evasion-decision.md`](../specs/anti-bot-evasion-decision.md),
   the corpus-release indicator policy). A capability with safety impact does
   not merge without either an SSG approval or a recorded decline.
2. **The Shield policy.** Ownership of the Shield's block thresholds,
   profiles, and ensemble membership (`docs/safety.md`,
   `packages/maverick-shield/`, the Shield v3 ensemble framework). Changes to
   what the Shield blocks by default are SSG decisions.
3. **The kill switch and revocation paths.** Oversight of
   `maverick/killswitch.py` and `maverick/revocation.py` — the controls that
   stop a running fleet and revoke trust. The SSG owns the policy for when
   they're exercised at the organization level (operators always retain their
   own local control).
4. **Incident review.** Post-incident review for any safety-relevant event
   (a successful injection in a supported config, a Shield miss, a capability
   misused as shipped), feeding fixes back into the threat model
   ([`docs/security/threat-model.md`](../security/threat-model.md)) and the
   `safety_report` annual.
5. **Release safety sign-off.** A go/no-go on the safety posture of each
   minor/major release, recorded against the SOC 2 evidence
   ([`docs/compliance/soc2-controls.md`](../compliance/soc2-controls.md),
   `maverick/soc2.py`) and the security-backport SLA
   ([`docs/security-backports.md`](../security-backports.md)).

### Out of scope

- **Routine code review** — owned by maintainers. The SSG is the escalation
  target, not a second reviewer on every PR.
- **Operator configuration choices** — Lightwork is operator-controlled by
  design; the SSG sets *defaults* and *what ships*, not what a given operator
  does in their own deployment.
- **Company HR/legal/process governance** — those belong to company
  governance, distinct from this body (cf. the SOC 2 doc's "Process-only"
  controls).

## Membership (roles to fill)

| Seat | Responsibility | Status |
| --- | --- | --- |
| Chair (safety lead) | Convenes the group, owns the agenda and the record | **TO STAFF** |
| Engineering representative | Speaks to feasibility and the control surface | **TO STAFF** |
| Security representative | Threat model, incident response, audit liaison | **TO STAFF** |
| Product/policy representative | User impact, the licensing/positioning frame | **TO STAFF** |
| Independent/community voice | An outside-the-team perspective once the project federates (cf. the 2028-H2 "elected TSC" governance v2) | **TO STAFF** |

Quorum is a simple majority of staffed seats; the Chair seat must be filled
for the body to act. Until seats are staffed, the **maintainer of record**
holds the SSG's responsibilities and records decisions under the same
process — so the paper trail is continuous, not retroactive.

## Decision process

1. A safety-significant change or question is raised (PR, issue, or incident).
2. It's framed as a decision: the question, the options, the safety argument
   for each — the same shape as the existing decision docs.
3. The SSG decides: **approve** (with conditions/guardrails noted),
   **decline** (with rationale and a revisit trigger), or **defer** (pending
   a named piece of evidence).
4. The decision is recorded — a `docs/specs/*-decision.md` for capability
   calls, an incident write-up for reviews, a line in the release checklist
   for sign-offs — and linked from the roadmap row it resolves.
5. Declines and approvals both carry a **revisit trigger** so a "no" is
   re-examinable when the facts change, not permanent by default.

## How this connects to what's already shipped

The SSG governs a control surface that already exists; it is not starting
from nothing:

- **Decision-doc trail** — `docs/specs/*-decision.md` (anti-bot evasion,
  Redis primary store, DuckDB, JIT, plugin API v3, learning substrate…).
- **Shield** — `packages/maverick-shield/`, ensemble framework + explainable
  reason codes (`docs/safety.md`).
- **Kill switch / revocation** — `maverick/killswitch.py`,
  `maverick/revocation.py`, `maverick/review_checkpoint.py`.
- **Audit + evidence** — append-only Ed25519 Merkle-chained audit log
  (`maverick/audit/`), `maverick/soc2.py` evidence collector,
  `maverick/safety_report.py` annual.
- **Disclosure + backports** — [`SECURITY.md`](../../SECURITY.md) (the vuln
  reward program), [`docs/security-backports.md`](../security-backports.md)
  (the LTS safety-branch SLA tooling).
- **Threat model + audit readiness** —
  [`docs/security/threat-model.md`](../security/threat-model.md),
  [`docs/security/audit-readiness.md`](../security/audit-readiness.md).

## Cadence

Quarterly standing review, plus on-demand for any release sign-off or
incident. The annual `safety_report` + `benchmark_retrospective` outputs are
the SSG's yearly review packet.
