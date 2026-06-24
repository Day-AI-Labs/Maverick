# Change Management Procedure

| Field | Value |
| --- | --- |
| Document ID | PROC-03 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | ISO 27001 A.8.31/A.8.32; ISO 42001 A.6.2; SOC 2 CC8.1 |

> This procedure operationalizes the Change Management Policy (POL-05). Where
> POL-05 sets the intent, this document is the step-by-step operating
> instruction the Organization follows to make, review, approve, deploy, and
> record changes to Maverick.

---

## 1. Purpose & scope

### 1.1 Purpose

To ensure every change to Maverick is authorized, reviewed by someone other than
the author, tested by automated controls, traceable to an approver, and
reversible. This is how the Organization satisfies SOC 2 CC8.1 (the entity
authorizes, designs, develops, tests, approves, and implements changes),
ISO 27001 A.8.32 (change management) and A.8.31 (separation of development,
test and production), and ISO 42001 A.6.2 (the AI system change lifecycle).

### 1.2 Scope

This procedure applies to all changes to:

- **Code** — anything tracked in the `Maverick` git repository: the kernel
  (`packages/maverick-core/`), shield, channels, dashboard, MCP, the installer
  apps under `apps/`, the TypeScript SDK under `sdks/plugin-ts/`, specialist
  packs/domains, and CI workflows under `.github/workflows/`.
- **Configuration** — runtime config (e.g. `~/.maverick/config.toml`, role/model
  mappings, budget caps, branch-protection settings, repository settings, secrets
  baselines `.secrets.baseline`, environment variables).
- **Infrastructure** — deployment manifests under `deploy/`, container images,
  hosting/runtime configuration, and any change to the production environment.

Out of scope: local developer experiments that never reach a shared branch, the
`main` branch, or a production environment. Once a change targets `main` or
production, it is in scope.

### 1.3 Roles

| Role | Responsibility |
| --- | --- |
| **Author** | Proposes the change; opens the PR; owns the description, tests, and rollback note. |
| **Reviewer / CODEOWNER** | Reviews and approves the PR. Must not be the author. Defined in `.github/CODEOWNERS`. |
| **Engineering Lead** | Owns this procedure; authorizes production deploys; runs the emergency/retroactive review. |
| **Management** | Approves this procedure and POL-05; named as deploy approver where the Engineering Lead is the author. |

---

## 2. Change types

Every change is classified into exactly one of three types. The author proposes
the type; the reviewer confirms it.

| Type | When it applies | Required approval |
| --- | --- | --- |
| **Standard** | The default. Any planned change to code, config, or infra delivered through a normal pull request. | ≥1 CODEOWNER review on the PR + all required CI gates green before merge. |
| **Expedited** | A time-sensitive but non-emergency change (e.g. a security patch, a customer-blocking defect) that must skip the normal queue/scheduling but **not** the controls. | Same as standard (≥1 CODEOWNER review + all required CI gates green). The Engineering Lead is notified and prioritizes review. No control is waived. |
| **Emergency** | Production is down or actively at risk and waiting for normal review/CI would extend material harm. | Verbal/written go-ahead from the Engineering Lead (or Management if the Lead is the author) **before** acting, then **retroactive PR review within 1 business day** (see §7). |

Notes:

- Expedited changes differ from standard only in **urgency and scheduling**, never
  in the controls applied. If you find yourself wanting to skip review or CI, the
  change is either standard (and must wait) or a genuine emergency (§7).
- An emergency change is the only path that may merge before a peer review
  completes, and it always incurs a retroactive review.

---

## 3. Standard change workflow (operator checklist)

Follow these steps in order. Paths cited are the actual controls in this repo.

- [ ] **1. Branch off `main`.** Create a feature branch; never commit directly to
      `main`. Use a Conventional-Commits-compatible branch name where practical.
- [ ] **2. Make the change as a surgical diff.** Match existing style; no
      speculative abstractions; state assumptions; write/adjust tests first for
      fixes and validation (Kernel rule 7).
- [ ] **3. New capability? Add the config knob AND the wizard step.** No new
      top-level dependency or capability without a config knob
      (Kernel rule 5) and a wizard step in
      `apps/installer-cli/maverick_installer/` (Kernel rule 6).
- [ ] **4. Open a pull request with a description.** The description states what
      changed, why, the change type (§2), test evidence, and a one-line
      **rollback note**. The PR title must follow Conventional Commits — a type
      prefix (`feat:`, `fix:`, `perf:`, `chore:`, `ci:`, `docs:`, `refactor:`,
      `test:`) and a subject starting with a **letter**.
- [ ] **5. Obtain a CODEOWNERS review.** At least one review from a code owner
      defined in **`.github/CODEOWNERS`** (added/maintained in this same change
      set). The approver must **not** be the author (§4). For files with a
      per-area owner (e.g. `/packages/maverick-core/`, `/deploy/`,
      `/.github/workflows/`), the matching owner reviews.
- [ ] **6. All required CI gates pass before merge.** Required workflows:
  - **`.github/workflows/ci.yml`**, jobs:
    - `lint` — `ruff check`, `vulture`, **detect-secrets** vs
      `.secrets.baseline`, and the custom gates run inside this job:
      `python -m maverick.plugin_matrix --ci`, `maverick domains-lint --ci`,
      `python -m maverick.deprecations --ci` (past-due deprecations fail),
      `python -m maverick.grpc_api.contract --check` (**additive-only**; proto
      removals/renumbers fail), `python -m maverick.a11y_audit --ci`,
      `python -m maverick.schema_migrations --ci`.
    - `audit` — dependency/security audit + SBOM.
    - `test` — the **test matrix on Python 3.10, 3.11, 3.12**.
    - `redteam`, `eval-smoke`, `postgres`, `docker` — as configured.
  - **`.github/workflows/conventional-commits.yml`**, job `lint-pr-title` — PR
    title check.
  - [ ] If any gate is red, fix forward on the branch. Do not merge a red PR and
        do not bypass a gate.
- [ ] **7. Squash and merge to `main`.** Use squash merge to keep `main` history
      linear and one commit per change. The squashed commit message keeps the
      Conventional Commits subject.
- [ ] **8. Confirm the merge commit is signed** (see §8) and the PR is linked to
      any tracking issue.

---

## 4. Segregation of duties (A.8.31 / CC8.1)

- **Author ≠ approver.** The person who opened a PR may never approve their own
  PR. The CODEOWNER review in step 5 must come from a different individual.
- **Development is separated from production.** Changes mature on feature
  branches and are validated by CI before they can reach `main`; only deploy-
  authorized roles promote `main` to production (A.8.31).
- **Who may approve a production deploy:** the **Engineering Lead** authorizes
  production deployments. Where the Engineering Lead is also the author of the
  change being deployed, **Management** provides the deploy authorization so that
  no single person both authors and unilaterally promotes their own change.
- **Single-maintainer reality and compensating control.** While CODEOWNERS
  currently resolves to one maintainer, the Organization compensates by
  (a) requiring all CI gates green (no human can wave a change through a red
  build), (b) requiring signed commits and an immutable audit trail (§8), and
  (c) requiring Management deploy authorization when the maintainer is the
  author. The CODEOWNERS structure is already laid out per package so additional
  reviewers can be added without restructuring (see `.github/CODEOWNERS`).

---

## 5. Recommended GitHub branch-protection settings **[Org action]**

The controls above are only as strong as the repository settings that enforce
them. The Organization applies the following branch-protection rule to `main`
in **GitHub → Settings → Branches → Branch protection rules** (or the equivalent
ruleset). Treat this section as a checklist to verify in repo settings.

- [ ] **Require a pull request before merging** (block direct pushes to `main`).
- [ ] **Require approvals: ≥ 1**, and **Require review from Code Owners**
      (enforces `.github/CODEOWNERS`).
- [ ] **Dismiss stale approvals when new commits are pushed.**
- [ ] **Require status checks to pass before merging**, and require these checks
      by name (the CI job names):
  - `lint`
  - `audit`
  - `test (3.10)`
  - `test (3.11)`
  - `test (3.12)`
  - `redteam`
  - `eval-smoke`
  - `postgres`
  - `docker`
  - `lint-pr-title` (from `conventional-commits.yml`)
- [ ] **Require branches to be up to date before merging.**
- [ ] **Require linear history** (consistent with squash-merge in §3 step 7).
- [ ] **Require signed commits** (consistent with §8).
- [ ] **Restrict who can push to `main`** to the deploy-authorized role(s) only;
      do **not** allow force pushes or branch deletion on `main`.
- [ ] **Include administrators / do not allow bypass** so the rule binds everyone.
- [ ] Re-verify these settings at each annual review of this procedure and
      whenever a CI job is added/renamed (a renamed job silently stops being a
      required check).

---

## 6. Production deployment checklist

A production deployment is itself a change and is authorized per §4.

### 6.1 Pre-deploy

- [ ] The exact commit being deployed is on `main` and **all CI gates were green**
      for that commit (§3 step 6).
- [ ] Deploy authorized by the Engineering Lead (or Management per §4).
- [ ] **Compliance posture verified** on the candidate build:
  - `maverick soc2` — collects SOC 2 control evidence and succeeds (the audit
    chain / control probe is healthy; see `packages/maverick-core/maverick/soc2.py`
    and `docs/compliance/soc2-controls.md`).
  - `maverick enterprise verify` — verifies the enterprise/deployment posture and
    writes the signed enterprise-verify probe (see
    `packages/maverick-core/maverick/deployment.py`).
- [ ] `maverick doctor` reports no blocking issues for the target environment;
      required secrets/keys present (a missing provider key degrades by design —
      `/healthz` returns 503 — so confirm intended).
- [ ] Rollback note from the PR is at hand (§3 step 4) and the previous known-good
      release tag/commit is recorded.

### 6.2 Deploy

- [ ] Promote `main` (or the tagged release) to production using the standard
      deploy mechanism under `deploy/`.
- [ ] Record start time, the commit SHA, and the operator in the change log (§8).

### 6.3 Post-deploy verification

- [ ] Health probes green: `/healthz`, `/livez`, `/readyz` on the dashboard app
      return the expected status (these are the auth-exempt LB probes; a 503 from
      `/healthz` means a degraded/missing-provider posture — investigate before
      declaring success).
- [ ] Re-run `maverick soc2` and `maverick enterprise verify` against the running
      production instance; confirm the audit chain is intact and the enterprise
      probe is signed.
- [ ] Smoke the CLI: `maverick version`, `maverick doctor`.
- [ ] No new error spikes / failed budget or shield events in the audit log.
- [ ] Mark the change log entry **Deployed — verified** with the end time.

### 6.4 Rollback procedure

Trigger rollback if any post-deploy check fails or a material regression appears.

- [ ] Engineering Lead authorizes rollback (a rollback is itself an authorized
      change; in an outage it follows the emergency path §7).
- [ ] Redeploy the previous known-good release tag/commit recorded in §6.1.
- [ ] If the change included a state/schema migration, apply the documented
      reverse migration (`maverick.schema_migrations`) — never leave production on
      a half-applied migration.
- [ ] Re-run §6.3 post-deploy verification against the rolled-back build.
- [ ] Log the rollback (cause, from-SHA, to-SHA, operator, time) and open a
      follow-up PR to fix forward.

---

## 7. Emergency change procedure

An emergency change is permitted **only** when production is down or actively at
risk and waiting for normal review/CI would extend material harm.

1. **Authorize before acting.** The Engineering Lead (or Management if the Lead is
   the author) gives an explicit go-ahead. Record who authorized it and when.
2. **Make the minimum change** to restore service. Prefer a rollback (§6.4) over a
   forward hotfix where possible.
3. **Run whatever CI you can.** Skipping a control is allowed *only* to the extent
   the emergency demands; run the full gate set as soon as the fire is out.
4. **Retroactive review within 1 business day.** Open (or back-fill) a PR for the
   emergency change with a full description and rollback note, have a CODEOWNER
   other than the author review it, and run the complete CI gate set. If review or
   CI surfaces a problem, remediate via a normal standard change.
5. **Log it.** Add a change-log entry flagged `EMERGENCY` capturing: trigger,
   authorizer, what changed, commit SHA, time of action, and the date the
   retroactive review completed. Emergency changes are reviewed in aggregate at
   the annual review of this procedure for patterns/abuse.

---

## 8. Change record & traceability

Every change must be reconstructable after the fact from durable records.

- **Pull request** — the primary record. Carries the description, change type,
  test evidence, rollback note, CODEOWNER approval, and the CI gate results. The
  PR is linked from the squashed `main` commit.
- **Signed commits** — commits are GPG/SSH-signed (and required by branch
  protection, §5), tying each change to an identity. Squash-merge yields one
  signed, attributable commit per change on a linear `main` history.
- **Audit log** — Maverick's signed, append-only audit chain records the
  deployment/posture events (`maverick enterprise verify` writes a signed probe;
  `maverick soc2` reads the audit chain). This provides tamper-evident evidence
  independent of GitHub.

### 8.1 Lightweight change-log expectation

In addition to the PR/commit trail, the Organization keeps a simple running
change log for **production deployments and emergency changes** (a markdown table
in the deployment runbook or release notes is sufficient). Each entry records:

| Date | Change type | PR / commit SHA | Author | Reviewer | Deploy authorizer | Result | Retroactive review (emergencies) |
| --- | --- | --- | --- | --- | --- | --- | --- |

- Standard, non-production changes do **not** need a separate log entry — the PR
  and signed commit are the record.
- Every production deploy and every emergency change **must** have a row.
- The change log is reviewed at the annual review of this procedure to confirm
  segregation of duties held and emergency changes were retroactively reviewed
  on time.

---

## 9. References

- POL-05 — Change Management Policy (parent policy).
- `.github/CODEOWNERS` — code-owner review assignments.
- `.github/workflows/ci.yml`, `.github/workflows/conventional-commits.yml` —
  required CI gates.
- `docs/compliance/soc2-controls.md`, `packages/maverick-core/maverick/soc2.py` —
  SOC 2 evidence.
- `packages/maverick-core/maverick/deployment.py` — `maverick enterprise verify`.
- `docs/compliance/control-crosswalk.md` — framework control mapping.
