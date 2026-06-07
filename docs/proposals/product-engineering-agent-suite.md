# Product & Engineering agent suite

**Status:** design / roadmap. Companion to the finance, IT-GRC, sales-GTM, and HR
suites; indexed in [`agent-suites-overview.md`](agent-suites-overview.md). Builds on
[`../enterprise/architecture.md`](../enterprise/architecture.md) and
[`agent-factory.md`](agent-factory.md). ~40 agents across eight towers.

> **Product & Engineering is the inverse of every other suite.** Finance and HR are
> greenfield *workflow*; here, **Maverick itself is a software-engineering agent**, so
> the engineering core — the recursive coding loop, sandboxed execution (7 backends),
> code review, the test-driven verifier, the SWE-bench eval harness, VCS/CI tools — is
> the most mature capability in the whole platform. And the connector layer is
> astonishingly complete: the `tools/` directory already ships **Jira, Linear, Asana,
> ClickUp, Trello, Notion, Confluence** (PM), **GA4, Mixpanel, PostHog, Plausible**
> (product analytics), **Datadog, Sentry, PagerDuty, Vercel, Cloudflare** (DevOps),
> `a11y` (accessibility), diagramming, and the full coding/VCS toolchain. **The tools
> are nearly all there; what's missing is the role-specialized agent personas (domain
> packs) that wield them, and a few workflow gaps.** This suite is *"wrap the richest
> existing toolset in role personas."*

The cardinal rule for every agent below (the P&E analogue of "never move money"):

> *Agents research, design, write, test, and review freely **in the sandbox** — but every
> execution is sandbox-mediated, code ships only through the **verifier + review** gates,
> a **human approves every merge to a protected branch, release, and production deploy**,
> product decisions (what to build) are human-owned, and **an agent never modifies its own
> runtime, safety, or controls without explicit human authorization.***

That last clause is unique to this suite: **Maverick builds Maverick**, so
self-modification is a first-class hard floor (see the shipped "disable self-edit writes
by default" control).

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How a P&E agent maps onto Maverick](#2-how-a-pe-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — eight towers](#5-the-roster--eight-towers)
   - [Tower 1 — Product Management](#tower-1--product-management)
   - [Tower 2 — Design & UX](#tower-2--design--ux)
   - [Tower 3 — Software Engineering (the kernel)](#tower-3--software-engineering-the-kernel)
   - [Tower 4 — Quality Engineering](#tower-4--quality-engineering)
   - [Tower 5 — DevOps / Platform / Release](#tower-5--devops--platform--release)
   - [Tower 6 — Data & ML Engineering](#tower-6--data--ml-engineering)
   - [Tower 7 — Developer Experience & Productivity](#tower-7--developer-experience--productivity)
   - [Tower 8 — Technical Research & Architecture](#tower-8--technical-research--architecture)
6. [The Engineering Supervisor (Layer A)](#6-the-engineering-supervisor-layer-a)
7. [Standards & governance packs (Layer B)](#7-standards--governance-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

This is the most "Shipped"-heavy reuse map of any suite.

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **The coding kernel** (recursive loop, edit formats, patch/AST edits, code exec) | `agent.py`, `coding_mode.py`, `edit_format.py`, `tools/{apply_patch,ast_edit,str_edit,code_exec,repo_map,dep_graph,test_impact}.py` | **Shipped** | Software Eng (T3) |
| **Sandboxed execution (7 backends + egress layer)** | `sandbox/{docker,podman,firecracker,kubernetes,devcontainer,ssh,local}.py` (7 backends) + `network_policy.py` (egress) | **Shipped** | every agent that runs code (§3.1) |
| **Code review** | `reviewer.py` + `/code-review` skill + GitHub Copilot review | **Shipped** | Code Review (3.2) |
| **Security review** | `/security-review` skill (+ IT-GRC AppSec, T7 there) | **Shipped** | review gate (§3.3) |
| **Test-driven verifier (anti-cheat)** | `verifier.py` | **Shipped** | the ship gate (§3.2), Test authoring (3.5) |
| **Eval / benchmark harness** (SWE-bench, GAIA, τ², terminal-bench) | `benchmarks/`, `continuous_benchmark.py` | **Shipped** | Eval (4.3), Release readiness (4.5) |
| **VCS / CI tools** | `tools/{git_advanced,github_actions,gitlab,bitbucket_tool}.py`, `github_app.py`, `issue_webhooks.py`, `webhooks.py` | **Shipped** | T3, T5 |
| **Multi-agent orchestration** | `swarm.py`, `orchestrator.py`, `task_graph.py`, `agent_bus.py`, `blackboard.py` | **Shipped** | the Supervisor (§6) |
| **Reasoning strategies** | `debate.py`, `reflexion.py`, `tree_of_thought.py`, `speculative.py` | **Shipped** | hard problems across T3/T8 |
| **Skills system** | `skills.py`, `skill_distillation_local.py`, `skill_embeddings.py`, `plugin_scaffold.py` | **Shipped** | Tooling (7.2) |
| **Chaos / resilience testing** | `chaos.py` | **Shipped** | Release readiness (4.5) |
| **PM / issue tracking** | `tools/{jira,linear,asana_tool,clickup_tool,trello_tool,notion,confluence_tool,airtable_tool}.py` | **Shipped** | Product Mgmt (T1) |
| **Product analytics** | `tools/{ga4_tool,mixpanel_tool,posthog_tool,plausible_tool}.py` | **Shipped** | Product Analytics (1.5), BI (6.5) |
| **Design / accessibility** | Figma (live MCP), `tools/{diagram_tool,a11y}.py`, Wix | **Shipped** | Design & UX (T2) |
| **DevOps / observability / cloud** | `tools/{datadog_tool,sentry_tool,pagerduty_tool,vercel_tool,cloudflare_tool,lambda_tool,s3_tool}.py`, `deploy/{docker,vps,github-action,gitlab-ci,homebrew,desktop}` | **Shipped** | DevOps (T5) |
| **Data / ML** | `tools/{sql_query,pandas_query,notebook_exec,spreadsheet,embeddings}.py`, `training/`, HuggingFace | **Partial** | Data & ML (T6) |
| **Docs** | `tools/{pandoc_tool,latex_tool,pdf_reader,ocr,knowledge}.py`, `docs/` | **Shipped** | Tech docs (7.1) |
| **Self-modification control** | `tools/self_edit.py` (writes disabled by default) | **Shipped** | the self-mod hard floor (§3.6) |
| **Least privilege / sandbox / budget / audit** | `capability.py`, `budget.py`, the signed audit chain | **Shipped** | every agent |
| **AppSec, AI-model governance, SRE/incident** | IT-GRC suite Towers 7 / 1 / 10 & 6 | cross-suite | T5, T6 (don't duplicate) |

**The genuine gaps:** the **role personas themselves** (PM, designer, data engineer as
domain packs — the tools exist, the agents don't), product-analytics-as-insight and
customer-feedback synthesis workflow, design-system governance, formal QA test-management,
ML model registry / MLOps depth, and **DORA / engineering-metrics**.

---

## 2. How a P&E agent maps onto Maverick

Each agent is one [`DomainProfile`](../../packages/maverick-core/maverick/domain.py)
pack — but here the pack is mostly **tool selection + persona over a shipped toolset**,
not new infrastructure. The Software Engineering tower (T3) is essentially the existing
coding agent with role-scoped capabilities; the other towers bind the already-shipped
PM/design/analytics/DevOps tools to specialist personas.

Two specifics:
- **The engineering agents are the most autonomous in the platform** (they write and run
  code), so the controls are about *what ships and what they're allowed to touch*, not
  about whether they can act.
- **Maverick builds Maverick.** Agents work on this very codebase, so self-modification,
  the verifier/review/CI gates, and human-approved merges are not abstract — they're the
  controls that keep an agent from changing its own safety substrate.

---

## 3. The control model (cross-cutting)

### 3.1 Sandbox-mediation (CLAUDE.md rule 4)
All execution goes through `sandbox.exec()` — never a raw `subprocess`. The 7 backends
(local → devcontainer → docker/podman → firecracker/kubernetes → ssh) + `network_policy`
give the operator the isolation/egress posture they need. **Shipped.**

### 3.2 The ship gate — verifier + review
Code ships only after the **test-driven verifier** (anti-test-cheating) passes *and* a
**code review** (and security review where warranted) clears. Agents draft PRs; they do
not merge unverified code. **Shipped** (`verifier.py`, `reviewer.py`, the skills).

### 3.3 Human-approved merge / release / deploy (maker-checker for code)
Merging to a protected branch, cutting a release, and **deploying to production** are
`require_human` (governance + consent). Agents prepare; humans approve. Production deploy
is a **hard floor** (§4.2).

### 3.4 Least privilege over the codebase & infra
Capability **path scopes** bound which repos/dirs an agent may touch and **host scopes**
which infra/registries it may reach; CI secrets are never exposed to agent context
(secret redaction). A docs agent can't touch infra; a data agent can't touch the kernel.

### 3.5 Supply-chain, secrets & licenses
Dependencies are license-scanned (`license_scan.py`) and (via IT-GRC AppSec, T7)
CVE/SBOM-checked; secrets are detected/redacted; MCP/plugins are pinned (`mcp_registry`
`pin_sha256`). Don't duplicate the AppSec tower — reuse it.

### 3.6 Self-modification hard floor (unique to this suite)
An agent must not modify its **own runtime, safety controls, or kernel** without explicit
human authorization — `tools/self_edit.py` ships with **writes disabled by default**.
Changes to `safety/`, `capability.py`, `governance.py`, the audit chain, or the sandbox
require a human and the full review gate. Maverick can improve Maverick, but never
silently weaken its own guardrails.

### 3.7 Product decisions are human-owned
*What* to build, prioritization, and tradeoffs are decided by humans (PM/leadership);
agents research, model, and recommend. The roadmap is not the agent's to set.

### 3.8 Budget, audit & provenance
Long-running engineering work respects `Budget`; every change, merge, and deploy is on the
signed audit chain; AI-generated code is marked/traceable (provenance).

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder (per action class)

| Level | Engineering behaviour |
|---|---|
| **L0 Observe** | analyze the codebase, review, recommend — no changes |
| **L1 Draft** *(default)* | open a PR / draft a spec; a human reviews & merges |
| **L2 Approve** | merge after human approval (the verifier + review must pass) |
| **L3 Auto-under-threshold** | auto-merge **low-risk** changes that pass CI + review — dependency bumps, docs, formatting, generated code in non-protected paths |
| **L4 Straight-through** | reserved; autonomous within a sealed, non-production scope (e.g. an internal tool's own repo) with post-hoc review |

### 4.2 Hard floors — never auto
- **production deployment** (always human);
- **self-modification** of the kernel / `safety/` / `capability` / `governance` / sandbox / audit (§3.6);
- **merge to a protected branch** without the verifier + review gate;
- adding a **strong-copyleft or critical-CVE dependency**;
- **disabling a CI/safety gate** or weakening a sandbox/egress policy;
- exfiltrating **source or secrets** beyond the allowed hosts.

### 4.3 Tech stack, repo topology & CI/CD
Languages/frameworks, monorepo vs polyrepo, branch-protection rules, the CI/CD system
(GitHub Actions / GitLab CI — both shipped), test/coverage thresholds, and which paths are
**auto-mergeable** (drives the L3 surface).

### 4.4 Enabled towers, sandbox posture & connectors
Which towers (a pure-software shop may skip Data/ML; a data team leans on T6), the sandbox
backend + network policy, and which PM/analytics/DevOps connectors are wired.

### 4.5 The Engineering Operating Profile
One signed, versioned bundle (intake produces, wizard edits, rule 6) compiling to
capability (path/host scopes) + governance policy + the auto-merge rules + the
self-modification floor + CI gates — the P&E analogue of the other suites' profiles.

---

## 5. The roster — eight towers

~40 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**, **Status**.
Most connectors are **shipped** (§1). Representative packs are full TOML.

---

### Tower 1 — Product Management

Tools shipped; personas are the gap.

#### 1.1 Product Discovery & Research Agent
- **Job:** User/market research, problem validation, opportunity assessment, jobs-to-be-done.
- **Connects to:** `web_search`, `tools/newsapi_tool`, user-feedback sources, `knowledge_search`.
- **Capability:** research + `draft_opportunity`. No commitments.
- **Status:** **Partial** (research shipped; persona gap).

#### 1.2 Roadmap & Prioritization Agent
- **Job:** Roadmap construction, prioritization (RICE/WSJF), tradeoff analysis.
- **Connects to:** `tools/{jira,linear,notion}` (shipped).
- **Capability:** read + `draft_roadmap`, `score_priority`. **Denies** committing the roadmap (human §3.7).
- **Status:** **Partial** (connectors shipped).

#### 1.3 Requirements & Spec (PRD) Agent
- **Job:** PRDs, user stories, acceptance criteria, edge-case enumeration.
- **Connects to:** `tools/{confluence_tool,notion,jira,linear}` (shipped).
- **Capability:** `draft_prd`, `draft_stories`. No prioritization decisions.
- **Status:** **Partial**.

```toml
# packages/maverick-core/maverick/domains/pe_product_manager.toml
name = "pe_product_manager"
compartment = "product_management"
description = "Product management: discovery, specs, roadmap support, analytics."

persona = """You are a Product Management specialist. Ground every recommendation in
evidence -- user research, product analytics, support themes -- and cite it. You DRAFT
PRDs, roadmaps, and prioritization analyses for a human product owner to decide; you do
NOT set the roadmap, commit priorities, or change scope yourself. Separate validated
learning from assumption, write crisp acceptance criteria, and name the riskiest
assumption in every spec."""

allow_tools = [
    "read_file", "web_search", "knowledge_search",
    "jira", "linear", "notion", "confluence_tool",
    "ga4_tool", "mixpanel_tool", "posthog_tool",
]
deny_tools = ["shell", "apply_patch", "self_edit"]
max_risk = "low"
knowledge_sources = ["product_strategy", "product_research"]
authoring = "manual"
```

#### 1.4 Backlog & Sprint Agent
- **Job:** Backlog grooming, sprint planning, ticket hygiene, estimation support.
- **Connects to:** `tools/{jira,linear,clickup_tool,asana_tool}` (shipped).
- **Capability:** read + `groom_backlog`, `draft_sprint`. Ticket writes gated.
- **Status:** **Partial**.

#### 1.5 Product Analytics & Insights Agent
- **Job:** Usage/funnel/retention analytics, experiment (A/B) analysis, insight synthesis.
- **Connects to:** `tools/{ga4_tool,mixpanel_tool,posthog_tool,plausible_tool}` (shipped), `sql_query`.
- **Capability:** read + `analyze_product_metrics`, `analyze_experiment`. No decisions.
- **Status:** **Partial** (analytics connectors shipped).

#### 1.6 Customer-Feedback Synthesis Agent
- **Job:** Synthesize feedback/reviews/support tickets into themes and product signals.
- **Connects to:** support (cross-ref GTM 6.x), `knowledge_search`.
- **Capability:** read + `synthesize_feedback`. No commitments.
- **Status:** **Partial**.

#### 1.7 Launch & Release-Coordination Agent
- **Job:** Launch plans, release notes, internal/GTM coordination.
- **Connects to:** GTM suite, `tools/{jira,linear}`, channels.
- **Capability:** `draft_launch_plan`, `draft_release_notes`. External comms gated (GTM).
- **Status:** **Gap** (coordination workflow).

---

### Tower 2 — Design & UX

#### 2.1 UX Research Agent
- **Job:** Usability studies, research synthesis, personas, journey maps.
- **Connects to:** `web_search`, research repos, `knowledge_search`.
- **Capability:** research + `synthesize_research`, `draft_personas`.
- **Status:** **Partial**.

#### 2.2 Interaction & UI Design Agent
- **Job:** UI design, wireframes, mockups, prototypes; design-to-code handoff.
- **Connects to:** **Figma** (live MCP, incl. Code Connect), `tools/diagram_tool`.
- **Capability:** `gen_design`, `prototype`. No publish to prod.
- **Status:** **Partial** (Figma connector shipped).

#### 2.3 Design-System Agent
- **Job:** Components, design tokens, consistency, design↔code sync.
- **Connects to:** **Figma** (Code Connect), the codebase (read).
- **Capability:** `manage_design_system`, `sync_tokens`. Code changes via the SWE gate.
- **Status:** **Partial**.

#### 2.4 Accessibility (a11y) Agent
- **Job:** WCAG audits, accessibility fixes, inclusive-design review.
- **Connects to:** `tools/a11y` (shipped), the codebase.
- **Capability:** `audit_a11y`, `draft_a11y_fix`. Fixes via the SWE gate.
- **Status:** **Partial** (`a11y` tool shipped).

#### 2.5 Content & UX-Writing Agent
- **Job:** Microcopy, content design, product voice, localization prep.
- **Connects to:** `knowledge_search`, `tools/translate`.
- **Capability:** `draft_microcopy`. Publish via product/release gate.
- **Status:** **Gap**.

---

### Tower 3 — Software Engineering (the kernel)

**This tower largely *is* the existing coding agent** — these are role-scoped
capabilities over the shipped kernel, not new builds.

#### 3.1 Implementation / Coding Agent
- **Job:** Feature implementation — the core code-write-test loop, against a spec/ticket.
- **Connects to:** the kernel (`agent`/`coding_mode`/`edit_format`), `tools/{apply_patch,ast_edit,code_exec,repo_map}`, the **sandbox**, VCS.
- **Capability:** edit-in-sandbox + `open_pr`. **Denies** merge (human §3.3) and `self_edit` (§3.6).
- **Status:** **Shipped** (the kernel).

```toml
# packages/maverick-core/maverick/domains/pe_software_engineer.toml
name = "pe_software_engineer"
compartment = "software_engineering"
description = "Feature implementation on a scoped repo (sandboxed, verifier-gated)."

persona = """You are a Software Engineer. Work test-first: reproduce or specify the
expected behavior as a test, then make it pass with the minimum change. Run everything in
the sandbox, match the surrounding code's style, and keep changes surgical. You open a
PR for human review -- you do NOT merge to a protected branch, deploy to production, or
modify the agent's own runtime/safety code. If the verifier or review fails, fix it; never
disable a gate to get green."""

allow_tools = [
    "read_file", "repo_map", "dep_graph", "knowledge_search",
    "apply_patch", "ast_edit", "code_exec", "shell", "git_advanced", "preview_diff",
]
deny_tools = ["self_edit", "github_actions", "vercel_tool", "cloudflare_tool"]  # no CI/deploy
allow_paths = ["src/**", "tests/**"]   # narrowed per engagement; never the safety substrate
max_risk = "high"                       # writes/exec code -- but sandbox-mediated + verifier-gated
knowledge_sources = ["eng_codebase", "eng_standards"]
authoring = "manual"
```

#### 3.2 Code-Review Agent
- **Job:** Review diffs for correctness, simplification, and reuse; enforce standards.
- **Connects to:** `reviewer.py`, the `/code-review` skill, GitHub Copilot review.
- **Capability:** read diffs + `review_diff`, `comment_pr`. No merge.
- **Status:** **Shipped**.

#### 3.3 Refactoring & Tech-Debt Agent
- **Job:** Refactor, modernize, reduce duplication, plan/execute tech-debt paydown.
- **Connects to:** `tools/{ast_edit,dep_graph,repo_map}`, the sandbox.
- **Capability:** edit-in-sandbox + `open_pr`. Same gates as 3.1.
- **Status:** **Shipped/Partial**.

#### 3.4 Debugging & Fix Agent
- **Job:** Reproduce, diagnose, and fix defects; root-cause analysis.
- **Connects to:** `tools/diagnose`, `code_exec`, the sandbox, `sentry_tool`.
- **Capability:** repro + fix-in-sandbox + `open_pr`.
- **Status:** **Shipped/Partial**.

#### 3.5 Test-Authoring Agent
- **Job:** Write unit/integration/E2E tests (TDD), raise coverage on risk.
- **Connects to:** `verifier.py`, `code_exec`, `test_impact`.
- **Capability:** write tests + `open_pr`.
- **Status:** **Shipped**.

#### 3.6 Code-Documentation Agent
- **Job:** Docstrings, API docs, READMEs, inline comments to house density.
- **Connects to:** `tools/{pandoc_tool,knowledge}`, the codebase (read).
- **Capability:** `draft_docs` + `open_pr`.
- **Status:** **Partial**.

---

### Tower 4 — Quality Engineering

#### 4.1 Test-Strategy Agent
- **Job:** Risk-based test plans, coverage strategy, test-pyramid design.
- **Connects to:** `knowledge_search`, `test_impact`.
- **Capability:** `draft_test_plan`. No prod changes.
- **Status:** **Gap**.

#### 4.2 Test-Automation Agent
- **Job:** Build/maintain automated suites (unit→E2E), reduce flakiness.
- **Connects to:** `code_exec`, the sandbox, `tools/browser`.
- **Capability:** write tests-in-sandbox + `open_pr`.
- **Status:** **Partial**.

#### 4.3 Eval & Benchmark Agent
- **Job:** Run the eval/benchmark harness, track regressions (SWE-bench/GAIA/τ²/terminal).
- **Connects to:** `benchmarks/`, `continuous_benchmark.py`.
- **Capability:** `run_eval`, `report_regression`.
- **Status:** **Shipped**.

#### 4.4 Bug-Triage & Quality-Analytics Agent
- **Job:** Triage incoming bugs, defect analytics, flakiness/quality trends.
- **Connects to:** `tools/{jira,linear,sentry_tool}`.
- **Capability:** read + `triage_bug`, `analyze_quality`. Ticket writes gated.
- **Status:** **Partial**.

#### 4.5 Release-Readiness & Chaos Agent
- **Job:** Release gates/checklists, chaos & resilience testing pre-release.
- **Connects to:** `chaos.py`, `benchmarks/`, the sandbox.
- **Capability:** `run_release_checks`, `run_chaos`. **Denies** the release decision (human).
- **Status:** **Partial** (`chaos.py` shipped).

---

### Tower 5 — DevOps / Platform / Release

(SRE/incident & AppSec overlap IT-GRC Towers 10/6/7 — cross-reference, don't duplicate.)

#### 5.1 CI/CD Pipeline Agent
- **Job:** Pipeline authoring/maintenance, build/test automation, gate config.
- **Connects to:** `tools/github_actions`, GitLab CI, `deploy/`.
- **Capability:** `draft_pipeline`. **Denies** disabling a gate (hard floor §4.2).
- **Status:** **Partial** (CI tooling shipped).

#### 5.2 Infrastructure-as-Code Agent
- **Job:** IaC (Terraform/Pulumi), provisioning, environment config.
- **Connects to:** `tools/{cloudflare_tool,vercel_tool,lambda_tool,s3_tool}`, cloud `‹build›`.
- **Capability:** plan-in-sandbox + `open_pr`. **Apply/provision gated** (human).
- **Status:** **Partial**.

#### 5.3 Release & Deployment Agent
- **Job:** Cut releases, orchestrate rollouts/canaries, rollback.
- **Connects to:** `deploy/`, `tools/{vercel_tool,github_actions}`, `checkpoint.py` (rollback).
- **Capability:** prepare release + `propose_deploy`. **Production deploy = hard floor (human).**
- **Status:** **Partial**.

#### 5.4 Observability & SRE Agent
- **Job:** Monitoring, SLOs, alert tuning, reliability. *(Cross-ref IT-GRC 10.3.)*
- **Connects to:** `tools/{datadog_tool,sentry_tool,pagerduty_tool}`, `observability.py`, `health.py`.
- **Capability:** read telemetry + `tune_alerts`, `draft_slo`.
- **Status:** **Partial** (observability + connectors shipped).

#### 5.5 Dependency & Supply-Chain Agent
- **Job:** Dependency updates, SBOM, vulnerability remediation. *(Cross-ref IT-GRC 7.2/7.4.)*
- **Connects to:** `license_scan.py`, `dep_graph`, advisory DBs `‹build›`.
- **Capability:** `propose_dep_update`. Copyleft/critical-CVE deps = hard floor.
- **Status:** **Partial** (license scan shipped; CVE/SBOM is the IT-GRC build).

---

### Tower 6 — Data & ML Engineering

#### 6.1 Data-Pipeline / Analytics-Engineering Agent
- **Job:** ETL/ELT, transformations (dbt-style), data models, pipeline maintenance.
- **Connects to:** `tools/{sql_query,pandas_query,notebook_exec}`, warehouses `‹build›`.
- **Capability:** model-in-sandbox + `open_pr`. Prod pipeline changes gated.
- **Status:** **Partial** (query/notebook tools shipped).

#### 6.2 Data-Quality & Governance Agent
- **Job:** Data quality tests, lineage, data contracts. *(Cross-ref GRC data governance.)*
- **Connects to:** warehouses `‹build›`, `pii_detector`.
- **Capability:** `test_data_quality`, `flag_lineage`. 
- **Status:** **Gap/Partial**.

#### 6.3 ML / Model-Development Agent
- **Job:** Model development, training, evaluation, experiment tracking.
- **Connects to:** `training/`, `tools/{embeddings,huggingface,notebook_exec}`, the sandbox.
- **Capability:** train/eval-in-sandbox + `open_pr`. Model promotion gated.
- **Status:** **Partial**.

#### 6.4 MLOps & Model-Deployment Agent
- **Job:** Model serving, monitoring, drift detection, retraining. *(Model cards/registry
  & AI risk → IT-GRC AI-Gov, T1 there.)*
- **Connects to:** serving infra `‹build›`, the IT-GRC AI-Gov tower.
- **Capability:** `draft_serving`, `monitor_drift`. Deploy gated.
- **Status:** **Gap**.

#### 6.5 BI & Reporting Agent
- **Job:** Dashboards, reports, self-serve analytics across the business.
- **Connects to:** `tools/{sql_query,spreadsheet,ga4_tool,mixpanel_tool}`, BI `‹build›`.
- **Capability:** read + `build_dashboard`, `build_report`.
- **Status:** **Partial**.

---

### Tower 7 — Developer Experience & Productivity

#### 7.1 Technical-Documentation Agent
- **Job:** Internal docs, runbooks, ADRs, API references, onboarding guides.
- **Connects to:** `tools/{knowledge,confluence_tool,notion,pandoc_tool}`, the codebase.
- **Capability:** `draft_tech_docs` + `open_pr`/publish-gated.
- **Status:** **Partial**.

#### 7.2 Internal-Tooling & Scaffolding Agent
- **Job:** Codegen scaffolds, internal CLIs/tools, plugin/skill scaffolding.
- **Connects to:** `plugin_scaffold.py`, `skills.py`, the sandbox.
- **Capability:** scaffold-in-sandbox + `open_pr`.
- **Status:** **Shipped/Partial** (`plugin_scaffold` shipped).

#### 7.3 Engineering-Metrics (DORA) Agent
- **Job:** DORA + flow metrics (deploy freq, lead time, MTTR, change-fail rate), bottlenecks.
- **Connects to:** `git_advanced`, `tools/{jira,linear}`, CI.
- **Capability:** read + `compute_dora`, `draft_eng_report`.
- **Status:** **Gap**.

#### 7.4 Developer-Support / Codebase-Q&A Agent
- **Job:** Answer "how does X work / where is Y", onboarding, codebase navigation.
- **Connects to:** `repo_map`, `knowledge_search`, the codebase (read).
- **Capability:** read + `answer_codebase`. Read-only.
- **Status:** **Partial** (repo_map + knowledge shipped).

---

### Tower 8 — Technical Research & Architecture

#### 8.1 Architecture & Design-Doc Agent
- **Job:** System design, ADRs, design reviews, tradeoff analysis.
- **Connects to:** `knowledge_search`, `tools/diagram_tool`, the codebase.
- **Capability:** `draft_design_doc`, `review_architecture`. No implementation decisions committed.
- **Status:** **Partial**.

#### 8.2 Technical-Investigation / Spike Agent
- **Job:** Research spikes, feasibility studies, throwaway PoCs in the sandbox.
- **Connects to:** the sandbox, `web_search`, the reasoning strategies (debate/ToT).
- **Capability:** experiment-in-sandbox + `report_findings`. PoCs don't ship without the gate.
- **Status:** **Shipped/Partial** (the kernel does this).

#### 8.3 Technology-Evaluation Agent
- **Job:** Library/framework/vendor evaluation, build-vs-buy, license/risk screening.
- **Connects to:** `web_search`, `license_scan.py`, `dep_graph`.
- **Capability:** evaluate + `draft_tech_eval`. No adoption decision.
- **Status:** **Partial**.

---

## 6. The Engineering Supervisor (Layer A)

Above the towers sits the **Engineering Supervisor** — the P&E instance of the oversight
control plane, and the most natural fit because the platform's **recursive swarm /
orchestrator already coordinate engineering sub-agents**. It:

- **routes & decomposes** a product goal across the towers (PM spec → design → implement →
  test → review → release), via `task_graph`/`orchestrator`/`swarm`;
- **owns the merge/release/deploy queue** — every protected-branch merge, release, and
  production deploy lands here for human approval, with the diff + verifier + review attached;
- **enforces the self-modification floor** — holds the parent capability; agents are spawned
  with path scopes that *exclude* the safety substrate unless a human authorizes;
- **holds the CI/auto-merge policy** and the budget.

Built on the shipped `swarm.py`/`orchestrator.py`/`task_graph.py` + `governance.py` +
`verifier.py` + `capability.py`; the operator console (the merge/deploy approval UI) is
the shared Layer-A gap.

---

## 7. Standards & governance packs (Layer B)

Engineering's "regimes" are standards + the org's own gates.

| Pack | Covers | Status |
|---|---|---|
| **Coding standards / style** | language/style/lint conventions, review rubric | **Partial** (`reviewer.py` + house style; per-client rubric to wire) |
| **Test & coverage policy** | verifier gates, coverage thresholds, eval gates | **Shipped** (`verifier.py`, `benchmarks/`) |
| **Branch protection / merge policy** | who/what can merge, required checks, auto-merge surface | **Partial** (governance + VCS; the merge-policy compiler) |
| **Secure-SDLC** | secret/SAST/SCA gates, threat modeling | **Partial** (reuse IT-GRC AppSec T7) |
| **Self-modification policy** | what an agent may change about itself | **Shipped** (`self_edit` off by default) — the keystone |
| **Accessibility (WCAG)** | a11y gates on UI | **Partial** (`a11y` tool) |
| **Data/ML governance** | data contracts, model cards, AI risk | **Gap** (reuse GRC + AI-Gov) |
| **Open-source / license policy** | allowed licenses, contribution policy | **Shipped** (`license_scan.py`) |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code):

| New `type` | Owner | Framework |
|---|---|---|
| `tech_design_review` | Architecture (8.1) | design-doc / ADR readiness checklist |
| `release_readiness` | Release (4.5) | go/no-go release gate |
| `prod_readiness` | DevOps (5.x) | operational-readiness review (SLOs, runbooks, rollback) |
| `dependency_risk` | Supply chain (5.5) | license + CVE + maintenance health |
| `data_pipeline_quality` | Data (6.2) | data-contract / quality checklist |
| `accessibility_audit` | a11y (2.4) | WCAG conformance |

Each becomes a `run_assessment` capability + a conversational assessor via
`build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle. **Most of
this is already shipped** (§1) — the rare ✅-heavy catalog.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **VCS / CI** | GitHub, GitLab, Bitbucket, GitHub Actions, GitLab CI | **✅ shipped** | T3, T5 |
| **PM / issue tracking** | Jira, Linear, Asana, ClickUp, Trello, Notion, Confluence, Airtable | **✅ shipped** | T1 |
| **Product analytics** | GA4, Mixpanel, PostHog, Plausible | **✅ shipped** | 1.5, 6.5 |
| **Design** | Figma (Code Connect), diagram, a11y, Wix | **✅ shipped/live** | T2 |
| **Observability / DevOps** | Datadog, Sentry, PagerDuty, Vercel, Cloudflare, Lambda, S3 | **✅ shipped** | T5 |
| **Data / compute** | SQL, pandas, notebooks, spreadsheet, HuggingFace, sandbox (7 backends) | **✅ shipped** | T6, T3 |
| **Docs** | pandoc, LaTeX, PDF, Confluence, Notion | **✅ shipped** | 7.1 |
| **Cloud platforms (deep IaC/CSPM)** | AWS, Azure, GCP | ◻ build (P2) | 5.2 |
| **Data warehouse / orchestration** | Snowflake, BigQuery, dbt, Airflow | ◻ build (P2) | T6 |
| **ML platform** | MLflow, SageMaker, Vertex | ◻ build (P3) | 6.3, 6.4 |
| **Feature flags / experimentation** | LaunchDarkly, Statsig | ◻ build (P3) | 1.5, 5.3 |

**Knowledge sources:** the codebase + `repo_map`, engineering standards/style guide, the
architecture docs (`docs/`), ADRs, the product strategy, and runbooks.

---

## 10. Build sequence

The kernel ships; lead with role personas + the gates, then close the workflow gaps.

1. **Role-persona packs over the shipped toolset (immediate).** Domain packs for the SWE
   (3.1), Code Review (3.2), PM (1.x), and Codebase-Q&A (7.4) agents — they're persona +
   tool-scope over the kernel and the shipped PM/analytics connectors. Plus the merge/
   release gates wired to `governance` + the **self-modification floor** asserted.
2. **The Engineering Supervisor** (§6) on the existing swarm/orchestrator — the merge/
   release/deploy approval queue and path-scope enforcement.
3. **QA + DevOps depth:** eval/release-readiness (4.3/4.5), CI/CD (5.1), observability
   (5.4) on the shipped tools; the assessment templates (§8).
4. **Design & UX** on Figma/a11y; **Product analytics & feedback synthesis** (1.5/1.6).
5. **Data & ML** (T6) on warehouse/ML connectors; **DORA metrics** (7.3).
6. **Vendor/cloud-deep connectors** (AWS/Azure/GCP IaC, warehouses, ML platforms).
7. **Wizard + dashboard** (rule 6): repo/CI setup, the Engineering Operating Profile /
   auto-merge / self-modification editor, and the merge/deploy console.

---

## 11. Honest caveats

- **Don't rebuild the kernel.** Tower 3 is the existing coding agent; the work is
  role-scoping + gating it, not reimplementing it. Same for the shipped PM/analytics/
  DevOps connectors — wrap them in personas, don't re-author them.
- **Agents draft; humans merge, release, and deploy.** No agent merges to a protected
  branch, cuts a release, or deploys to production on its own — those are gated human acts,
  and **production deploy is a hard floor**.
- **Self-modification is the load-bearing control.** Because Maverick builds Maverick, an
  agent changing its own runtime/safety/kernel without human authorization would undermine
  every other suite's controls. `self_edit` ships off by default — keep it that way and
  route any safety-substrate change through a human + the full review gate.
- **Verifier + review are not optional.** "Get to green by disabling the gate" is the
  failure mode the anti-test-cheating verifier exists to stop; the gate is the product.
- **Product decisions stay human.** Agents inform *what* to build; they don't decide it.
- **Reuse the neighbors.** AppSec → IT-GRC T7; SRE/incident → IT-GRC T10/6; model
  governance → IT-GRC T1; ESG/data-governance → GRC. Cross-reference, don't fork.
