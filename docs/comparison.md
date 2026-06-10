# Maverick vs the field

Maverick is a self-hosted, governed, auditable agent runtime: a recursive
multi-agent swarm that runs in your environment, on the models you choose,
under hard budget caps. The products it gets compared to — Devin, Hermes,
OpenClaw, Cline, Aider — are good at what they do, but they sit in different
categories with different trade-offs. This page maps the dimensions so you can
decide which category fits your problem.

Two ground rules for reading it:

- **Maverick claims are grounded in [`FEATURES.md`](./FEATURES.md)** — every
  cell cites the shipped module or count behind it.
- **Competitor columns describe categories, not scorecards.** Hosted agents,
  CLI coding agents, and agent frameworks each have a characteristic shape;
  individual products vary and change fast. Verify specifics against each
  vendor's own documentation — we don't publish claims about competitor
  internals here.

## The categories

- **Hosted autonomous dev agents** (Devin-class): a vendor-operated cloud
  service. You hand it a task; it runs in the vendor's environment.
- **CLI coding agents** (Aider, Cline-class): an agent in your terminal or
  editor, focused on interactive work in one repository.
- **Agent frameworks & runtimes** (Hermes, OpenClaw-class): self-hostable
  agent software you run and extend yourself; scope and surface vary widely
  by project.

## Dimensions

| Dimension | Maverick | Hosted autonomous dev agents | CLI coding agents | Agent frameworks & runtimes |
|---|---|---|---|---|
| **Deployment model** | Self-hosted: laptop, Docker, VPS, Kubernetes, or air-gapped with no required egress. Proprietary, commercially licensed. | Vendor-hosted, zero-ops; your tasks and data run in the vendor's cloud. | Local process in your terminal/editor; you supply API keys. | Self-hostable; ops burden is yours; licensing varies by project. |
| **Governance / compliance surface** | RBAC + OIDC, capability tokens (`capability.py`), per-tool ACLs, consent ledger (`safety/consent.py`), approval delegation, per-principal spend quotas (`quotas.py`), compliance profiles (`compliance_profiles.py`, e.g. HIPAA), finance governance with amount-tiered authorization (`maverick/finance/`). | Vendor-managed controls; evaluate the vendor's attestations and data-handling terms. | Minimal by design — a human is in the loop for each session. | Build-your-own; depth varies by project. |
| **Multi-agent topology depth** | Recursive orchestrator spawns parallel specialist sub-agents (`orchestrator.py`, `swarm.py`); verifier default-on, reflexion, graded critic; tree-of-thought, debate, plan-execute-reflect; shared blackboard + cross-agent bus. | Topology is vendor-defined and not user-configurable. | Typically a single-agent edit loop scoped to one repo. | Varies — from single-agent gateways to composable graphs; check each project. |
| **Channel / tool breadth** | 100+ built-in tools incl. ~47 SaaS connectors; 14 chat/voice/wearable channels (`packages/maverick-channels/`); consumes external MCP servers as tools. | Vendor-curated integrations, usually web-UI-first. | Focused toolset around the repo: editor, git, shell; some speak MCP. | Plugin/skill ecosystems of varying size; check each project. |
| **Sandboxing** | 7 selectable backends — local subprocess, Docker, SSH, Podman, devcontainer, Firecracker microVM, Kubernetes (`sandbox/`) — plus per-tool network egress policy (`sandbox/network_policy.py`). | Vendor-managed isolation in the vendor's cloud. | Commands typically execute in your local environment; isolation is your setup. | Varies; often delegated to your deployment. |
| **Auditability** | Signed, hash-chained append-only audit log (`maverick audit verify`), SIEM export, encryption-at-rest, DSAR, data-retention enforcement, replayable run traces (`replay_trace.py`). | Session histories and vendor-side logs; export and retention depend on the vendor. | Local chat/session logs. | Varies; usually logging you wire up yourself. |
| **Extensibility** | `@tool` decorator, hot plugin reload, MCP server *and* client, A2A Agent Cards, gRPC API, LangChain/LangGraph adapter, cross-language quickstarts (TS/Go/Rust/C#/Java). | Limited to what the vendor exposes. | Config and conventions; some support MCP servers. | Extension model *is* the product; shape varies. |

## When NOT to choose Maverick

An honest list. Pick something else if:

- **You want a hosted, zero-ops service.** Maverick is self-hosted by design;
  you operate it. If "someone else runs the infrastructure" is a requirement,
  a hosted agent is the right category.
- **You only need interactive, single-file code edits.** A CLI pair-programming
  agent is a lighter, faster fit. Swarm orchestration, budgets, and audit
  plumbing are overhead for that job.
- **You require an open-source license today.** Maverick is proprietary and
  commercially licensed. A stripped-down open-source "lite" edition is a
  possibility on the [roadmap](./ROADMAP.md), not a commitment.
- **You need an embedded non-Python library.** The kernel is Python (3.10+).
  Other languages drive Maverick over MCP or gRPC — they don't link it in.
- **You need a stability guarantee right now.** Maverick is alpha. It is
  installable and tested (2000+ tests across Python 3.10/3.11/3.12), but APIs
  can still move.

## Verify it yourself

Don't take a comparison table's word for it — the repo ships runnable
evaluation harnesses under [`benchmarks/`](../benchmarks/):

- **GAIA**, **τ²-bench-style** stateful, **terminal-bench-style**, and
  **SWE-bench** harnesses, plus a **moat suite** — CI-runnable on shipped
  fixtures.
- **Long-horizon tasks** (`benchmarks/longhorizon/`) reproducible from a
  single `maverick start` command, with expected wall-clock and cost ranges
  documented in [`benchmarks/README.md`](../benchmarks/README.md).

```bash
maverick start "$(cat benchmarks/longhorizon/research-report.md)" \
  --max-dollars 5 --max-wall-seconds 1800 --workdir bench-workspace
```

Record results in `benchmarks/RESULTS.md` with the run metadata (date, model
assignments, total cost). Run multi-seed before trusting any single number —
including ours; single-run benchmark figures are directional, not proof.
