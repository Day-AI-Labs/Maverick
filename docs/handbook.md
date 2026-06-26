# The Lightwork Handbook

**The front door.** One document that explains what Lightwork is, how to
think about it, how to drive it, how to operate it, and where everything
deeper lives. Every command and module named here exists in the tree;
counts come from [`FEATURES.md`](./FEATURES.md), the catalogue of shipped
features. When this page and the code disagree, the code wins and this
page is the bug.

Lightwork is **proprietary, commercially licensed software**
([`LICENSE`](../LICENSE)) — self-hosted in your environment, but use
requires a license. A stripped-down open-source "lite" edition is a stated
possibility on the [roadmap](./ROADMAP.md), not a commitment.

---

## 1. What Lightwork is

A **governed agent runtime**: a recursive multi-agent swarm wrapped in the
runtime primitives most agent frameworks skip — hard budgets, sandboxed
execution, a signed tamper-evident audit log, attenuating capabilities,
and a content shield. You hand it a goal; an orchestrator decomposes it,
spawns specialist sub-agents (researcher, coder, writer, verifier) that
work in parallel, verifies their output, and returns a result. Every step
runs under a spending cap you set, through safety chokepoints, on models
you choose.

It targets enterprises and regulated teams that need agents they can
**govern, audit, and run entirely in their own environment** — laptop,
Docker, VPS, Kubernetes, or an air-gapped network — and technical users
who want the deepest agent framework available. The useful mental frame is
an operating system: an OS multiplexes processes onto hardware under
isolation, permissions, and resource limits; Lightwork multiplexes *agents*
onto LLMs and tools under the same kinds of controls. (A lens, not a brand
— see [`architecture.md`](./architecture.md) for why.)

## 2. The mental model — five primitives

Everything in the runtime hangs off five ideas. Module paths are relative
to `packages/maverick-core/maverick/` unless noted.

### The swarm

The kernel (`orchestrator.py`, `agent.py`, `swarm.py`) runs a recursive
loop: decompose the goal, spawn sub-agents per sub-task, execute tools,
verify, integrate. Verification is default-on (`verifier.py`), failed
attempts retry with memory of why they failed (`reflexion.py`), and a
graded critic gives structured accept/revise/reject feedback
(`critic.py`). Richer planning topologies are available when a task
warrants them: tree-of-thought, debate, plan-execute-reflect
(`maverick plan-reflect GOAL`), speculative and latency-aware best-of-N.
Spawning is capped (fan-out and total-spawn limits) so recursion can't run
away.

### The world model

Persistent state lives in a SQLite database with FTS5 full-text search
(`world_model.py`) under `~/.maverick/` — goals, episodes, turns,
conversations, facts, approvals. It survives restarts: `maverick resume`
continues interrupted goals, `maverick history` and `maverick logs` read
back what happened, and facts (`maverick fact` / `maverick facts`) persist
across runs. A Postgres backend (`[world_model] backend = "postgres"`)
serves shared/hosted deployments, tenant-stamped on every root table.

### The budget

A hard ceiling the kernel refuses to exceed (`budget.py`): dollars,
wall-clock, tokens, and tool calls, checked in the loop — not advisory
logging after the fact. Set per run (`maverick start --max-dollars 2.0`),
per provider per day/month (`[budget.provider_caps]`), and per principal
(`quotas.py`). `maverick budget` shows total and per-run history;
`maverick cost` breaks down spend; `maverick budget-tune` *recommends* a
cap from your history (a human sets it). A house rule: no code path
bypasses `budget.check()`.

### The shield

Agent Shield (`packages/maverick-shield/`) screens content at **three
chokepoints**: input (the prompt), tool call (before execution), output
(before delivery). With the full SDK installed you get its detector set;
without it, a built-in rule set runs — secrets, PII, jailbreak heuristics,
unicode/zero-width tricks, phishing patterns. The shield is a chokepoint,
not a hard dependency: the kernel runs without it, **failing open with a
loud warning, never silently** — a house rule. An adversarial corpus
gates every CI run (`python -m maverick_shield.redteam`).

### The sandbox

All shell execution is mediated — no tool calls `subprocess.run` directly;
everything routes through `sandbox.exec()` (also a house rule). Nine
selectable backends (`sandbox/`, `[sandbox] backend`): local subprocess,
Docker, Podman, gVisor (Docker with the `runsc` userspace kernel),
devcontainer, Kubernetes, Firecracker microVMs, SSH, and Modal cloud
sandboxes. Third parties ship backends without forking via the Sandbox SDK
v2 entry-point contract (`sandbox/sdk.py`). The interface itself is
formally modeled and TLC-verified in TLA+
([`docs/specs/tla/`](./specs/tla/README.md)).

Two more threads run through all five: **per-role model choice** — you
pick the models, per role, from 12 providers (`llm.py`; Anthropic, OpenAI,
OpenRouter, Ollama, Gemini, DeepSeek, Bedrock, Azure, xAI, Moonshot, TGI,
vLLM), configured in `~/.maverick/config.toml`, never hard-coded — and the
**audit log**, a signed, hash-chained, append-only record of every action
(`audit/`), verifiable offline.

## 3. A guided tour

The 90-second path:

```bash
pipx install 'maverick-agent[installer]'
maverick init          # wizard: four questions, safe defaults (--fast skips)
maverick start "Research the three best static site generators for a docs \
site, compare them in a table, and scaffold the winner" --max-dollars 2.0
```

Watch it work from a second terminal:

```bash
maverick monitor       # live Rich plan-tree TUI of the swarm
maverick status --cost # goal states + live spend
maverick logs          # the audit trail of what it did
```

Interact and steer:

```bash
maverick chat                  # REPL — each line is a goal
maverick answer 3 "June 14"    # answer a question a running agent asked
maverick resume 7              # continue an interrupted goal
maverick halt                  # killswitch: stop everything now
maverick unhalt                # re-arm
```

Make it recurring and reachable:

```bash
maverick schedule goal "0 7 * * *" "Summarize my GitHub notifications"
maverick worker                # drains the scheduled-job queue
maverick serve                 # channel server: Telegram/Discord/Slack/...
maverick dashboard             # web UI + REST API at http://127.0.0.1:8765
maverick mcp                   # MCP server: drive Lightwork from Claude Code,
                               # Cursor, or any MCP client
```

Extend it:

```bash
maverick skill install gh:Day-AI-Labs/maverick:benchmarks/example-skills/web-research.md
maverick skills                # list installed + distilled skills
maverick template browse       # community goal templates
maverick plugin list           # installed plugins + permissions
```

And keep yourself honest:

```bash
maverick doctor                # green/yellow/red health check
maverick dream                 # nightly: consolidate experience (cron-friendly)
maverick hindsight --ledger    # weekly: record the improvement curve
maverick proof --days 30       # monthly: the value report for the business
maverick budget                # what it has cost you
maverick audit verify          # prove the log hasn't been tampered with
```

Useful flags worth knowing early: `maverick start --dry-cost` (forecast
before spending), `--template NAME --param k=v` (parameterized goals),
`maverick init --fast` (defaults) and `--resume` (continue a half-finished
wizard).

## 4. Operating it

### Configuration

One file: `~/.maverick/config.toml`. `maverick config show / path / edit`
gets you there; the full schema is documented in
[`configuration.md`](./configuration.md), and `maverick migrate` walks an
old config forward (dry-run by default). Defaults live in code; overrides
live in the file. Per-role models go under `[models]`
via `maverick.config.get_role_model(role)`; secrets interpolate from env
(`${VAR}`) rather than living in the file. Every optional capability —
channels, providers, sandboxes, plugins — has a config knob, and the
installer wizard (`apps/installer-cli/`) can enable each one, because the
wizard is the source of truth for UX.

### Identity & access

`maverick whoami` reports your principal. Enterprise deployments map SSO
users in via OIDC ID tokens or a reverse-proxy identity header, dropping
into role-based access control (`[roles.<role>]`) and the capability model
(`capability.py`): Ed25519-signable grants that only *narrow* as they
propagate to child agents, with revocation that reaches agents mid-run
(`maverick capability revoke`). Consent prompts gate destructive actions
(`MAVERICK_CONSENT_MODE`); `maverick governance show / check` explains the
live policy and what it would decide. See
[`security-hardening.md`](./security-hardening.md).

### Tenancy

Multi-tenant deployments wall each tenant into
`~/.maverick/tenants/<t>/` (`workspace.py`, `paths.py`) with a per-tenant
world DB; isolation is pinned by a dedicated test suite
(`tests/test_multitenant_isolation.py`). The control plane on top:
`maverick tenant create / list / suspend / resume / quota / delete`
(roster + per-tenant daily spend caps), `maverick billing invoice /
entitlements` (metering → invoices, plan entitlements), per-tenant
envelope encryption with a KMS-wrapped key per tenant (`tenant/kms.py`),
and a per-tenant egress policy (`tenant/egress.py`). The channel server
enforces the roster at the door.

### Audit, compliance, retention

The audit log is append-only NDJSON, Ed25519-signed and hash-chained:

```bash
maverick audit tail            # recent entries
maverick audit grep PATTERN    # search it
maverick audit verify          # offline chain verification
maverick audit seal            # seal day files
maverick audit export          # date-windowed SIEM export
```

Around it: encryption-at-rest (`maverick encryption migrate`), SOC2
readiness (`maverick soc2`), DSAR export (`maverick dsar export`), GDPR
erasure with differential proof (`maverick erase`, `maverick erase-verify`),
ROPA and DPIA generators (`maverick ropa`, `maverick dpia`), the EU AI Act
helper (`maverick ai-act`), compliance posture (`maverick compliance
--strict`), and regime packs for finance (`maverick finance status`).
Retention is enforced, not aspirational: `maverick retention enforce
[--dry-run]` prunes audit files, episode/event rows, and usage-ledger
buckets per `[retention]` policy; `maverick gc` collects old goal data.

### Day-2 operations

[`operations.md`](./operations.md) is the runbook (hung service, crashed
process, runaway spend, backup/restore of `world.db`). Quick diagnostics:
`maverick doctor`, `maverick ps` (unified process table), `maverick diag
circuits / ratelimits / health / cost-by-tag`, `maverick failures` (the
distribution of *why* runs fail), `maverick analytics` (DuckDB OLAP over
your history), `maverick cost-retro` (where the money went). Observability
is opt-in OpenTelemetry + Prometheus `/metrics` (`observability.py`);
performance holds a published SLA you can re-measure
(`python -m maverick.perf_sla --ci`, [`perf-sla.md`](./perf-sla.md)).
Deployment blueprints for Kubernetes / ECS / Fly.io / Railway live in
[`reference-architectures.md`](./reference-architectures.md).

## 5. The safety model

Defense in depth, each layer independent:

1. **Budget** — the hard resource ceiling (primitive #3). A runaway agent
   is, at worst, a capped agent.
2. **Shield** — content screening at input / tool-call / output
   (primitive #4), with explainable reason codes (`shield_ensemble.py`).
3. **Sandbox** — execution isolation (primitive #5), plus per-tool network
   egress policy (`sandbox/network_policy.py`) and an Enterprise-mode
   egress lock.
4. **Capabilities & consent** — least privilege that only attenuates
   downward; destructive actions gated on a human; risk auto-classified
   before a goal runs (`safety/goal_risk.py`).
5. **Killswitch** — `maverick halt` (or touching `~/.maverick/HALT`)
   aborts all running goals (`killswitch.py`); long runs can also demand a
   periodic human heartbeat (`[safety] review_checkpoint`).
6. **Audit** — everything recorded, signed, verifiable after the fact.

These are not just claimed; they are *tested at roster scale*. A governance
invariant test suite verifies six invariants across all 2,020 packs — (1)
tool-reachability (no drafting/non-builder agent can reach a state-mutating
tool), (2) the autonomy dial (an onboarding agent, or any high-risk action, is
never autonomous), (3) capability attenuation (a spawned child can never exceed
its parent grant), (4) compartment isolation (a quarantine seal never bleeds
across compartments/suites), (5) hard refusals (the universal refusal floor is
unstrippable), and (6) budget caps (no cap is ever silently exceeded) — each
fault-injected at 1,000,000 iterations with a non-vacuity control, alongside
hostile-argument fuzzing of every connector and tool.

Posture checks make claims testable: `maverick airgap check` fails if the
config has any outbound path (remote provider, non-deny-all egress,
networked sandbox); `maverick confidential-compute` detects SEV-SNP/TDX;
`maverick enterprise verify` checks the enterprise-mode floor. The
red-team corpus gates CI on every commit, and the threat model is written
down ([`security/threat-model.md`](./security/threat-model.md)).
Vulnerabilities: [`SECURITY.md`](../SECURITY.md).

## 6. Extension points

Six sanctioned ways to extend the runtime — all behind config knobs, all
screened by the same shield/budget/sandbox machinery:

- **Skills** — markdown procedures (`SKILL.md`: name, triggers, steps)
  the agent applies when a goal matches. `maverick skill install / browse /
  validate`, schema in
  [`benchmarks/example-skills/README.md`](../benchmarks/example-skills/README.md).
  Lightwork can also *learn* skills from its own successful runs, opt-in
  (`[self_learning]`, [`self-learning.md`](./self-learning.md)).
- **Plugins** — Python entry points under plugin API v2
  ([`plugin-api-v2.md`](./plugin-api-v2.md)): declared manifests, enforced
  permissions, a version lockfile (`maverick plugin lock / verify`),
  opt-in subprocess/subinterpreter isolation, and a CI compatibility gate
  (`python -m maverick.plugin_matrix --ci`). `maverick plugin new`
  scaffolds one. Non-Python authors: the **TypeScript plugin SDK**
  (`sdks/plugin-ts/`, `@maverick/plugin-sdk`) and a **gRPC plugin host**
  for any language. Single Python tools need only the `@tool` decorator
  (`tools/decorator.py`).
- **Channels** — 17 wired adapters (`packages/maverick-channels/`):
- **Connectors & primary-source grounding** — 214 write-capable enterprise
  REST/GraphQL connectors plus 37 read-only primary-source / public-data
  connectors (SEC EDGAR, FRED, Treasury, World Bank, FDIC, Census, BLS, EIA,
  openFDA, NPPES, ClinicalTrials, USAspending, SAM.gov, CourtListener, Federal
  Register, GLEIF, OpenCorporates, NWS/NOAA, EPA, ...), plus dedicated-module
  connectors (Salesforce, HubSpot, Stripe, ServiceNow, Snowflake, ...). The 37
  public-data connectors are auto-granted per analyst suite for primary-source
  grounding (GET-only, low-risk, deferred); on by default, kill-switch
  `[workforce] data_grounding = false` (or `MAVERICK_WORKFORCE_DATA_GROUNDING=off`),
  with an installer wizard step.
  Telegram, Discord, Slack, Signal, Email, Matrix, Bluesky, Mastodon,
  Voice, WhatsApp (Twilio + Cloud API), SMS, iMessage, IRC, Threads, RCS,
  and a glasses/wearable bridge. New ones subclass `Channel` in `base.py`
  — four steps, documented in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
- **MCP, both directions** — `maverick mcp` exposes the swarm to any MCP
  client (stdio + Streamable HTTP); `[mcp_servers]` makes Lightwork
  *consume* external MCP servers as tools, which still pass through the
  shield. `maverick mcp-registry browse / add` manages sources.
- **APIs & language clients** — the dashboard's REST API
  ([`api.md`](./api.md)), the contract-gated gRPC v1 surface
  ([`grpc.md`](./grpc.md)), A2A Agent Card interop ([`a2a.md`](./a2a.md)),
  LangChain/AutoGen/CrewAI adapters, and quickstarts for TypeScript, Go,
  Rust, C#, and Java (`docs/clients/`). Deliberately *not* a port: other
  languages drive Lightwork over the wire; the kernel stays Python (the
  council decision in [`ROADMAP.md`](./ROADMAP.md)).
- **Sandbox backends** — the entry-point contract from primitive #5;
  conformance-checked, refused if non-conformant.

Providers get added in three files plus tests (CONTRIBUTING "Adding a
provider"). Whatever you extend: shield wired or it doesn't count, budget
respected, sandbox-mediated, config knob + wizard step — the house rules
in [`CLAUDE.md`](../CLAUDE.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md)
are short and enforced.

## 7. Where everything lives

The full map. Start at [`getting-started.md`](./getting-started.md) if you
haven't installed yet.

| You want | Go to |
|---|---|
| Install + first run | [`getting-started.md`](./getting-started.md), README |
| Every shipped feature | [`FEATURES.md`](./FEATURES.md) |
| What's *not* built yet | [`ROADMAP.md`](./ROADMAP.md) (+ [`ROADMAP-2029-2031.md`](./ROADMAP-2029-2031.md)) |
| The architecture argument | [`architecture.md`](./architecture.md), [`docs/specs/`](./specs/) decision memos |
| Config schema | [`configuration.md`](./configuration.md), [`env-vars.md`](./env-vars.md) |
| Deploy targets | [`deployment.md`](./deployment.md), [`reference-architectures.md`](./reference-architectures.md), [`github-action.md`](./github-action.md) |
| Run it day-2 | [`operations.md`](./operations.md), [`perf-sla.md`](./perf-sla.md) |
| Safety & security | [`safety.md`](./safety.md), [`security-hardening.md`](./security-hardening.md), [`security/`](./security/), [`SECURITY.md`](../SECURITY.md), [`threat-hunting.md`](./threat-hunting.md) |
| Enterprise & compliance | [`enterprise/`](./enterprise/) (editions, security overview, diligence), [`regulated-deployment.md`](./regulated-deployment.md), [`compliance/`](./compliance/), [`encryption.md`](./encryption.md) |
| Extend it | [`plugins.md`](./plugins.md), [`plugin-api-v2.md`](./plugin-api-v2.md), [`self-learning.md`](./self-learning.md), [`embedding.md`](./embedding.md), [`connectors.md`](./connectors.md) |
| Drive it from outside | [`api.md`](./api.md), [`grpc.md`](./grpc.md), [`a2a.md`](./a2a.md), [`clients/`](./clients/), [`integrations/`](./integrations/) |
| Task recipes | [`cookbook/`](./cookbook/) (30 recipes), [`starter-goals.md`](./starter-goals.md) |
| How it compares | [`comparison.md`](./comparison.md), [`benchmarks/`](../benchmarks/) (`EVAL.md`, `RESULTS.md`) |
| Community & programs | [`showcase.md`](./showcase.md), [`programs/`](./programs/) (summit, office hours, grants, awards, partnerships…) |
| Press & naming | [`press-kit.md`](./press-kit.md), [`TRADEMARK.md`](../TRADEMARK.md) |
| Contribute | [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`CLA.md`](../CLA.md), [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md), [`MAINTAINERS.md`](../MAINTAINERS.md) |
| Licensing | [`LICENSE`](../LICENSE), [`enterprise/editions.md`](./enterprise/editions.md) |

### The honest closing note

Lightwork is alpha. It is installable today, carries 2000+ tests in CI, and
the features in this handbook ship and run — and parts of the frontier are
explicitly unfinished, which the roadmap states plainly, including the
things that were considered and declined. That discipline — shipped vs.
planned vs. declined, never blurred — is the most load-bearing convention
in this repository. Hold this handbook to it: if you find a claim here the
code can't back, that's a bug; file it.
