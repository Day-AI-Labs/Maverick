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
