# Competitive landscape & positioning

> Working strategy note, not a contract. The agent-platform space moves fast —
> re-verify vendor specifics before quoting them externally. The point of this
> doc is the *shape* of the market and where Lightwork's wedge is.

## The one-line position

**The self-hostable, governed, auditable agent _runtime + control plane_ —
integrated.** Lightwork runs the agents *and* governs them, in the customer's own
environment. Most of the market does one of those two, hosted.

## The five camps

"Enterprise agentic platform" is crowded, but the players cluster into five
camps, and almost nobody integrates **runtime + governance + self-host** at once.

| # | Camp | Examples | Strong at | Weak at (vs. Lightwork) |
|---|---|---|---|---|
| 1 | **Frameworks → platforms** | LangChain/LangGraph + LangSmith, Microsoft AutoGen / Semantic Kernel, CrewAI, LlamaIndex, Meta Llama Stack | Developer mindshare, building agents | Governance is bolted on; mostly hosted or BYO-ops |
| 2 | **Hyperscaler agent platforms** | AWS Bedrock AgentCore, Google Vertex Agent Builder / Agentspace, Azure AI Foundry Agent Service + Copilot Studio, OpenAI AgentKit | Distribution, models, scale | Can't be self-hosted in a regulated / air-gapped environment |
| 3 | **Governance / AgentOps / security** | Credo AI, CalypsoAI, Holistic AI, OneTrust; Langfuse, Arize, Braintrust, LangSmith; Lakera, Lasso, Prompt Security, HiddenLayer | Policy, eval, observability, agent security | A *layer* — they observe/gate someone else's runtime; no runtime of their own |
| 4 | **RPA incumbents pivoting** | UiPath (Agentic Automation), Automation Anywhere, Power Automate | Regulated install base, governance muscle, distribution | Not an open, deep multi-agent kernel; legacy automation DNA |
| 5 | **Coding / vertical agents** | Devin (Cognition), Cursor, Cline, Aider, Sierra, Glean, Writer, plus OpenClaw / Hermes | A specific high-value job | Different buyer; not a horizontal governed platform |

## Where Lightwork actually competes

Not as "another agent framework" — camp 1 owns that mindshare and we won't win a
framework popularity contest. Not as "a hosted agent runtime" — camp 2 wins on
distribution. The wedge is the **integration the others structurally lack**:

- Camps 1–2 have the **runtime** but not deep, self-hosted **governance**.
- Camp 3 has the **governance** but no **runtime** — they're bolt-ons.
- Camp 4 has governance + install base but not an **open, deep multi-agent
  kernel**.

Lightwork is the bet that **regulated / enterprise teams need the runtime and the
governance to be the same thing, in their own environment** — exactly the
three-layer control plane in [`enterprise/architecture.md`](../enterprise/architecture.md):
oversight control plane (every action flows through it), compliance-regime
engine, per-employee fleets.

## The moat (and the honest risks)

**Moat: self-host.** Data residency, air-gap, "our auditors need the evidence in
our environment," sector regulation. This is the durable answer to camp 2 —
hyperscalers will keep adding governance to their runtimes, but they cannot offer
*run it entirely in your VPC / on-prem with the governance baked in*. The deepest
buyers (finance, health, public sector, defense) screen on exactly this.

**Risks to stay honest about:**

1. **Hyperscalers add governance.** Bedrock AgentCore / Azure AI Foundry are
   moving this way. Compete on self-host + depth of governance, not on a feature
   checklist we'd lose.
2. **Governance point-tools are well-funded** (camp 3). Our answer: they can't
   *run* the agent; we govern from inside the loop, not from a sidecar.
3. **Surface sprawl.** We have an enormous capability surface and no named design
   partner yet. The wedge above only converts with one regulated ICP driving it.

## Why the experience matters here

The buyer for the self-hosted governed platform is a **supervisor / risk owner**,
not just a developer. Camps 1 (CLI/SDK-first) and 3 (dashboards without a
runtime) are both weak on a *self-hosted supervisor experience that makes
governance tangible* — a live view of what the fleet is doing, why, at what cost
and risk, with one-click intervention. That experience is both our UX gap and a
competitive moat; see [`ux/oversight-experience.md`](../ux/oversight-experience.md).
A great oversight console is the demo that wins the deal.

## Objection handling — "why not just use X?"

**"…a hyperscaler agent platform (Bedrock AgentCore, Vertex, Azure AI Foundry, OpenAI AgentKit) already governs agents."**
They govern agents hosted *on their cloud, inside their walls*. They can't run entirely in the customer's VPC / on-prem / air-gap with governance baked in — exactly what the deepest regulated buyers screen on. Maverick is the self-hosted, integrated answer, and governs across *multiple* clouds.

**"…a governance / AI-security point tool (Credo AI, Lakera, Prompt Security, Langfuse) covers this."**
Sidecars — they observe or gate *someone else's* runtime. Maverick governs from inside the loop (every action flows through the control plane) and runs the agent, so it can enforce attenuating capabilities, per-action approval, and a signed replay of the *actual* execution — which a bolt-on cannot.

**"…we'll build it in-house."**
The primitives are individually buildable; the assembled, tested, self-hostable governed runtime *with a cryptographic flight recorder* is a multi-year effort — and it already ships (see below).

**"…LangGraph / CrewAI / AutoGen is our agent stack."**
Keep it. Maverick governs agents built on any framework; we compare against *governance platforms*, never the runtime SDK.

**"…UiPath / Automation Anywhere already have governance + our install base."**
Legacy RPA DNA, not an open, deep multi-agent kernel for non-deterministic agents. We are the agentic successor with governance native, not retrofitted.

## Proof the wedge is real (shipping in `main` today)

The wedge — *runtime + governance + self-host, integrated* — is code, not a roadmap (~9,300 tests):

- Tamper-evident **Ed25519 hash-chained audit** + a **standalone external verifier** (`maverick-verify-audit`) an auditor runs with no trust in us.
- **Signed run replay + one-click evidence packets**; high-risk actions bracketed with sealed before/after screenshots.
- **Attenuating capabilities** (per-call tokens, subtree revocation) + a **per-action human-approval gate** on computer/browser actuations.
- **Cross-agent trust plane + permission graph**, **discovery** (inventory by risk), and **pre-action simulation** ("why allowed/blocked" before it runs).
- **Enterprise mode** (fail-closed egress lock + at-rest sealing) with an **enforceable preflight** that refuses to boot an under-hardened deployment; OIDC/RBAC/tenant isolation; container sandboxing; Helm self-host.

This is the "self-hosted supervisor experience that makes governance tangible" the five camps structurally lack — and the demo that wins the deal.
