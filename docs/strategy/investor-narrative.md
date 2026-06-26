# Maverick — Investor Narrative

> Draft v1. Status-honest: claims about the product are grounded in code that is
> merged in `main` today (see [Proof](#5-proof-its-already-real)). Claims about
> the market, the round, and the team are marked **[FILL IN]** where they depend
> on facts the authors must supply. Time-sensitive competitor facts are marked
> **[verify]**.

---

## The one sentence

**Maverick is the governed execution and evidence layer for autonomous AI agents in regulated enterprises** — a **self-hostable, integrated agent runtime + control plane** that runs the agents *and* discovers, constrains, simulates, audits, and *proves* what every agent did, across every model and tool, inside the customer's own boundary.

We win on **governance, provable behavior, and self-host** — with the runtime and the governance *integrated*, not bolted together. We don't enter the runtime popularity contest; we win where regulated enterprises actually block: control and evidence. (Companion docs: [`competitive-landscape.md`](./competitive-landscape.md), [`moat-and-acquisition.md`](./moat-and-acquisition.md), [`design-partner-scorecard.md`](./design-partner-scorecard.md).)

---

## 1. Category

**Self-hostable governed agent runtime + control plane — integrated.** Maverick runs its own governed agents *and* extends that governance to heterogeneous agents (open-source, third-party, MCP, internal). Model-agnostic, tool-agnostic, deployed inside the customer's boundary. Most of the market does *either* runtime *or* governance, hosted; Maverick does both, self-hosted — the system of record and control for autonomous workers.

If the last decade gave enterprises IAM for humans and CI/CD for code, the next gives them a **control plane for autonomous workers**. That is the category, and it is forming now.

## 2. Why now

- Agents are leaving demos and entering production: they *act* — call APIs, move data, send messages, trigger workflows, spend money.
- An autonomous agent is a new class of privileged, **non-deterministic** actor. The tools enterprises bought for humans (IAM), code (CI/CD), and APIs (gateways) were not designed for a worker that improvises.
- Security, legal, and audit are now in the room. The questions are concrete: *Who owns this agent? What can it reach? What did it do? Why? Can you prove it?*
- Regulation is arriving (EU AI Act transparency/logging, model-risk management, sector rules) and turns "we logged it" into "produce tamper-evident evidence."
- The incumbents are validating the category from both sides — workflow platforms adding agent "control towers," security vendors acquiring the LLM/agent traffic layer **[verify: ServiceNow/Google governance push; Palo Alto's gateway acquisition]**. Validation *and* threat. The opening is a neutral, self-hostable control point that governs across all of them.

## 3. The problem (concretely)

A bank, insurer, or health system wants agents to do real work — close the books, reconcile claims, triage tickets, run vendor payments. The blocker is never "can the agent do it." It is:

- **Discovery** — nobody can enumerate the agents, tools, MCP servers, and credentials already in the building (shadow AI).
- **Least privilege** — agents inherit broad, standing permissions; there is no attenuating, per-action authority.
- **Containment** — a wrong autonomous action (pay, send, delete, deploy) is hard to prevent and harder to undo.
- **Evidence** — when the CISO/auditor/regulator asks "what happened and why," the answer is application logs that anyone could have edited.
- **Boundary** — for PHI/PCI/PII/classified data, none of this can leave the customer's environment.

These are *governance* problems, and they are unsolved by the runtime vendors whose incentive is to make the agent do *more*, faster.

## 4. Why existing tooling doesn't cover it

- **Agent frameworks** (LangGraph, CrewAI, AutoGen, OpenAI/Google agent tools) help you *build* agents. They are not a governance/evidence layer and are not neutral across ecosystems.
- **Enterprise platforms** (ServiceNow, Salesforce, Microsoft, Google) govern *their own* agents inside *their own* walled garden — not the open-source/custom/third-party agents a real enterprise also runs.
- **AI gateways / LLM security** (Palo Alto/Portkey, Lakera, Prompt Security) sit on model traffic. Necessary, but they stop at the prompt/response — not the *agent's identity, capabilities, approvals, and replayable actions across tools*.
- **GRC/compliance** (Vanta, Drata, OneTrust) automate *company* controls, not the runtime behavior of an autonomous agent.

Maverick is the layer that spans these: identity + capabilities + policy + telemetry + audit + replay + simulation + evidence, for any agent, inside the customer's boundary.

## 5. Proof: it's already real

This is the differentiator. Most agent startups at this stage have a demo. Maverick has a **governed, auditable runtime with a cryptographic flight recorder**, ~9,300 tests, and a standalone verifier — all in `main`:

- **Tamper-evident audit** — Ed25519 hash-chained, append-only event log with cross-file anchoring; a **standalone Rust binary (`maverick-verify-audit`)** lets an external auditor prove a log is intact with no Python and no trust in us (byte-exact, cross-language parity-tested).
- **Signed run replay + evidence packets** — reconstruct any run's full action timeline (tool calls, approvals, blocks), verify the chain, and export a one-click JSON evidence bundle for a CISO/auditor. High-risk actions are bracketed with **sealed before/after screenshots**.
- **Attenuating capabilities** — provably narrowing per-principal grants; short-lived, single-use per-tool tokens; instant revocation of an entire delegation subtree.
- **Per-action approval gate** — governed computer/browser actuations (a click on "Pay," a "transfer" keystroke) route through a human approval queue; high-impact verbs escalate automatically; typed secrets never reach the audit log.
- **Cross-agent trust plane + permission graph** — a registry of external agents with pinned keys and tool/risk/budget/direction ceilings, rendered as a directed graph.
- **Discovery + pre-action simulation** — inventory every tool/MCP server/provider/channel/agent by risk; dry-run any proposed action to see its risk and gate decision *before* it runs.
- **Hard budgets** — token/$/wall/tool caps enforced at record time; concurrent-safe.
- **Enterprise mode** — fail-closed egress lock + at-rest sealing, with an **enforceable preflight** that refuses to boot a deployment claiming hardening it doesn't actually have. OIDC/PKCE SSO, RBAC, per-tenant isolation (Postgres RLS).
- **Self-hostable** — Helm chart, container sandboxing (docker/podman/gVisor/…), MCP interop. Nothing has to leave the customer boundary.
- Plus a **library of 2,020 specialist packs across 53 suites** as ready-made, governed use cases.
- **Primary-source data grounding** — every analyst pack is auto-granted 37 read-only primary-source / public-data connectors by suite (SEC EDGAR, FRED, Treasury, World Bank, FDIC, Census, BLS, EIA, openFDA, CourtListener, ...); GET-only, low-risk, ON by default with an env/config kill-switch and a wizard step, so claims are grounded in authoritative sources, not just model memory.
- **Roster-wide governance invariants, fault-injected** — six invariants (tool-reachability, autonomy dial, capability attenuation, compartment isolation, hard refusals, budget caps) verified across all 2,020 packs and fault-injected at 1,000,000 iterations, each with a non-vacuity control, plus hostile-argument fuzzing of every connector and tool. This is the test evidence behind the governance claims.

The honest framing: each primitive is individually copyable; *the assembled, tested, self-hostable governed runtime is a multi-year build* — and it already exists.

## 6. The wedge & ICP

Lead with **one urgent buyer and one workflow**, not the whole menu. Two viable wedges (recommend picking one to start):

- **A — CISO / AI security:** "Discover and govern every AI agent before it becomes the next shadow IT." Timely, budgeted, acquirer-relevant. Crowded; needs trust proof (we have the evidence story).
- **B — Regulated operations / compliance:** "Run AI agents on regulated workflows (finance close, claims, vendor payments) with approvals, data boundaries, and cryptographic evidence." Matches the codebase's depth; high ACV; slower sales.

**Recommended:** lead with **governance + audit + containment** (B-flavored, sold to a regulated ops + security buyer jointly), using the specialist packs as use-case proof — *not* "2,020 agents."

**ICP:** regulated mid-market/enterprise (fintech, insurance, healthcare ops, security operations, compliance-heavy SaaS) that is actively piloting agents and has a CISO/compliance veto.

## 7. The moat

Features get copied; control points compound. **The durable moat is self-host** — data residency, air-gap, and "our auditors need the evidence in *our* environment" are requirements hyperscaler- and SaaS-native platforms structurally can't meet, and the deepest regulated buyers (finance, health, public sector, defense) screen on exactly this. On top of that:

1. **The evidence graph** — a cryptographically-verifiable record of every agent action, replayable and attributable. Hard to retrofit; it has to be designed in from the first event.
2. **Capability inheritance** — an attenuating authority model enforced across heterogeneous agents.
3. **Cross-vendor agent registry** — governing agents we didn't build is the neutral position incumbents structurally won't take.
4. **Policy simulation + replay/causality** — "why allowed/blocked" before and after, not just passive logs.
5. **Switching cost** — customer-specific learning, packs, and the accumulated Operating Record.
6. **Externally verifiable** — beyond self-host, the audit chain is *independently* provable via a standalone binary (no trust in us, no Python). "Runs in our boundary *and* we can verify it ourselves" is hard for SaaS-native competitors to match.

## 8. GTM & milestones (next two quarters)

- **3 lighthouse design partners** in the chosen ICP (one paid pilot).
- **1 flagship demo**: a governed vendor-payment/claims workflow that *blocks* a risky autonomous action, routes it to approval, and ends with an exported, chain-verified evidence packet.
- **1 external security artifact**: SOC 2 Type I underway + a scoped third-party pentest.
- **1 benchmark report**: unsafe-action prevention/recording rate across N agent-attack scenarios vs. workflow completion.
- **1 repeatable ROI metric** and **1 case study**.
- **[FILL IN]** any existing pilots/LOIs/usage to insert as traction.

## 9. The ask

- **Raising:** **[FILL IN amount / stage]** to fund: design-partner delivery, SOC 2 + pentest, the benchmark, and 2–3 GTM/forward-deployed hires.
- **Use of funds → milestone:** convert 3 design partners into 2–3 paying lighthouse logos and a defensible benchmark within ~2 quarters.

## 10. Team

**[FILL IN]** — founders, relevant security/enterprise/AI background, why this team wins this category. (For a security-control-point company, lead with security + enterprise-distribution credibility.)

---

### Appendix — status honesty

| Area | State |
|---|---|
| Governed runtime, signed audit, capabilities, replay, evidence, discovery, simulation, enterprise mode, self-host | **In `main`, tested** |
| Standalone Rust audit verifier; browser DOM/a11y bridge | **In `main`, tested** |
| SOC 2 Type II attestation, third-party pentest | **In progress / not yet** |
| Paying customers, revenue, design partners | **[FILL IN]** |
| Remote/sandboxed desktop for computer-use; multi-tenant SaaS at scale | **Roadmap** |

We would rather be trusted on a small honest claim than caught on a big one. The technical claims above are verifiable in the repository today.
