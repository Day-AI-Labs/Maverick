# Roadmap Additions — Gap Analysis (May 2026)

> **Reconciled against shipped code — June 2026.** Many items below have since
> landed. See **[Reconciliation status](#reconciliation-status-june-2026)** for the
> at-a-glance done/open table. Section bodies are kept verbatim for context, with
> corrections inline where the original text is now factually wrong (C1, C3).
> Legend: ✅ shipped · 🟡 partial · ⬜ open.

A companion to [`ROADMAP.md`](./ROADMAP.md). That doc is the broad 36-month
backlog; **this one is a focused gap analysis**: what the roadmap *under-weights*
given (a) what the code itself admits is unfinished and (b) how the agent
ecosystem moved in 2026.

**Method.** A code-level sweep for stubs / `NotImplementedError` / "scaffold" /
"for now" markers across the kernel, tools, providers, sandboxes, and channels;
plus an ecosystem scan of MCP protocol changes, 2026 frontier-model agent
features, agent-interop standards, competitor capabilities, and eval practice.

**Thesis.** The existing roadmap is *breadth-heavy* (hundreds of tools, channels,
integrations). The highest-value additions are not more breadth — they cluster in
three places the roadmap under-invests:

1. **The agent-loop control surface** — durable/resumable execution, checkpoints,
   lifecycle hooks, provider-neutral context lifecycle.
2. **The MCP / interop layer the whole cross-language strategy rides on** — the
   MCP *server* is on an old spec.
3. **Closing Maverick's own learning & eval loop** — the RL/PRM/compaction
   machinery is scaffolded but open, and there's no eval harness.

Items are tagged **[near-term]** (next 1–2 quarters) or **[strategic]**. Each
cites evidence: `file:line` for code gaps, or a source theme for ecosystem items.
See the **Accuracy caveats** at the bottom — several ecosystem dates/specs
postdate the author's knowledge and must be re-verified before they become
roadmap commitments.

---

## Reconciliation status (June 2026)

*Reconciled against the code on `main`. ✅ shipped · 🟡 partial · ⬜ open. PR
numbers cite where it landed; `file:line` cites the implementing code.*

| Item | Ask | Status | Evidence |
|------|-----|--------|----------|
| **A1** | Durable/resumable execution + checkpoint/rewind | ✅ shipped | `checkpoint.py` (store + `latest()`), `cli.py` `resume` |
| **A2** | Kernel lifecycle hooks (Pre/PostToolUse, UserPromptSubmit) | ✅ shipped | `hooks.py` |
| **A3** | Context lifecycle — deferred tool loading / memory tool / programmatic calling | 🟡 partial | deferred loading + `find_tools` shipped (#693); compaction in `compaction.py`/`context_compactor.py`; **memory-tool + programmatic tool-calling still open** |
| **B1** | Tool `outputSchema` | ✅ shipped | `server.py` `outputSchema` on tools |
| **B1** | Resource subscriptions | ✅ shipped (#694) | `http_transport.py` `resources/subscribe` |
| **B1** | Streamable-HTTP transport | ✅ present | `http_transport.py` (not deprecated SSE) |
| **B1** | Elicitation | ⬜ open | deliberately unadvertised; needs a design for the sync loop |
| **B1** | Async tasks | ⬜ open | — |
| **B2** | MCP client OAuth 2.1 + Registry | ⬜ open *(blocked)* | client is **stdio-only** (`mcp_client.py`); needs a remote-HTTP client transport first |
| **B3** | A2A vs. homegrown ACD | ⬜ open *(decision)* | — |
| **C1** | Eval harness (GAIA / τ²-bench / terminal-bench) | 🟡 GAIA shipped (#687) | `benchmarks/eval_gaia.py`, `evals.py`; τ²/terminal-bench adapters still open |
| **C1** | Skill quality gate / pruning | 🟡 partial | quality gate (#396) + usage decay (`skills.py::_decay_weights` → `skill_stats`); explicit versioning/active-pruning still light |
| **C2** | Learning-substrate decision (close loop vs. prune) | ⬜ open *(decision)* | `training/`, `prm.py`, compaction gate are scaffolds |
| **C3** | Verifier default-on across goal types | ✅ confirmed | `agent.py:1155–1342` — `verify_final` runs on every orchestrator depth-0 FINAL, not coding-gated |
| **D1** | Shared tool-reliability layer | ✅ shipped (#684) | `tool_reliability.py`, `retry.py` |
| **D2** | Semantic memory wired into reflexion | ✅ shipped (#678) | `reflexion.py` cosine path (fastembed) |
| **D3** | Session-provider tool-use gaps | ✅ shipped (#685) | de-scoped + documented |

**Net:** the cleanly-autonomous Lane A/B engineering is largely done. What's left
clusters into (a) two MCP server items that need design — **elicitation, async
tasks**; (b) a **prerequisite** (remote-HTTP MCP *client* transport) that unblocks
**OAuth/Registry**; (c) finishing **A3** (memory/programmatic calling) and **C1**
(more benchmark adapters); and (d) the **decisions** — C2 learning substrate, B3
A2A-vs-ACD, and the breadth-vs-depth question (see
[`tool-inventory.md`](./specs/tool-inventory.md)).

---

## A. Agent-loop control surface (highest leverage; reinforces the long-horizon wedge)

### A1. Durable, resumable execution + checkpoint/rewind **[near-term]**
The single biggest miss. Maverick's pitch is "works for hours, pause overnight,
resume," and it has a persistent *world model* — but **no per-step checkpoint of
agent state, no crash-resume, no rewind/fork**. Competitors now treat this as the
long-horizon backbone (Claude Code `/rewind`; LangGraph durable execution +
time-travel from any `checkpoint_id`). Add a pluggable checkpoint store (file +
agent state) with crash-resume and rewind/fork. *This is the addition most
aligned with the stated wedge.*

### A2. Lifecycle hooks as the canonical chokepoint **[near-term]**
Add kernel-level `PreToolUse` / `PostToolUse` / `UserPromptSubmit` hooks. This is
competitor table-stakes (Claude Agent SDK ~25 hook points; OpenAI Agents SDK
guardrails), but for Maverick it's more than parity: it's the clean seam that
unifies the **shield**, **budget checks**, and **killswitch**, which are wired
ad-hoc at the turn/tool boundary today. The roadmap lists "plugin lifecycle
hooks" but frames them as a *plugin* feature, not the kernel's central gate.

### A3. Provider-neutral context-lifecycle layer **[near-term]**
The code is *waiting* on this: `compaction.py` hardcodes the keep/drop boundary
"until we have outcome reward end-to-end," and 80+ tools + external MCP servers
blow tool-definition context. Wire up generically (Anthropic-native, emulated
elsewhere):
- a **memory + context-editing** abstraction (server-side compaction / persistent
  memory tool),
- **tool search / deferred tool loading** so tool defs don't dominate context,
- **programmatic tool calling** routed through the existing `sandbox.exec()`
  chokepoint, keeping intermediate tool results out of context.

All three serve long-horizon depth *and* the 12-provider story directly.

---

## B. The MCP / interop layer Maverick bet on (must-fix)

### B1. Finish the MCP *server* spec adoption **[near-term]**
**Correction (verified against current `server.py`):** an earlier draft of this
doc said the MCP server is "hand-rolled on protocol `2024-11-05`." That is
**stale** — the server already advertises **`2025-11-25`** with proper version
negotiation (down to `2024-11-05`) and already implements **resources** and
**prompts**. The cross-language strategy rides on this surface, so the remaining
work is narrower than "modernize," but real:
- **Elicitation** — explicitly *not* wired today (the capability is deliberately
  unadvertised so 2025-11-25 clients don't hang; `ask_user` is used instead).
  This is the highest-value remaining item: it maps cleanly onto the shield's
  consent UI (form mode + URL mode for secrets that must never enter model
  context).
- **Async Tasks** (the `2025-11-25` long-running-task lifecycle) — absent; the
  natural fit for Maverick's hours-long runs over a stateless transport.
- **Structured tool `outputSchema`** — declare result shapes so clients/LLMs know
  what to expect.
- **Resource subscriptions** — `subscribe` is currently `false`; live goal/skill
  updates would let clients stream progress.
- **Transport + remote auth** (client *and* server side): confirm streamable-HTTP
  (not deprecated SSE) in `http_transport.py`, and add **OAuth 2.1 / PKCE** for
  consuming/exposing remote servers (see B2).

### B2. MCP *client* maturity — OAuth 2.1 + Registry + allowlist governance **[near-term]**
To consume *remote* MCP servers, the client needs a real OAuth 2.1 / PKCE flow
(and the "no token passthrough" rule is a shield concern). Consuming the official
MCP **Registry** with installer-wizard **allowlist controls** also gives the skill
marketplace a real discovery backbone.

### B3. A2A: scaffold → signed Agent Cards + real task lifecycle; resolve build-vs-adopt **[strategic]**
A2A matured into a Linux-Foundation standard (signed Agent Cards, gRPC transport,
broad adoption). The roadmap meanwhile invents a *homegrown* "ACD"
capability-descriptor spec — swimming against a consolidating standard.
**Recommendation:** adopt A2A's Agent Card as the descriptor and reframe or cut
ACD. (`AGNTCY`/OASF agent-identity is a further-out bet worth tracking.)

---

## C. Close Maverick's own learning & eval loop (credibility of the "deepest agent" claim)

### C1. Built-in eval harness across ≥3 benchmarks + distillation-quality measurement **[near-term → strategic]**
Today eval is SWE-bench-centric (`benchmarks/`). Ship a harness that runs a local
subset of **GAIA / τ²-bench / terminal-bench** (different slices: general
assistant / tool-agent-user policy adherence / CLI ops) and reports per-benchmark
scores. Separately, auto-distilled skills have **no quality gate, no versioning,
no "did it help," no pruning** — a bad skill can *poison future runs*
(`skills.py`), which is a safety issue, not just a feature. You can't claim
"deepest long-horizon agent" without measuring it.

> **Update (June 2026):** partly addressed — a skill **quality gate** landed
> (#396) and skill retrieval now uses **usage-based weight decay**
> (`skills.py::_decay_weights` → `skill_stats`). Explicit **versioning** and
> **active pruning** remain light. The GAIA half of the eval harness shipped
> (#687); τ²-bench / terminal-bench adapters are still open.

### C2. Decide the learning-substrate question **[strategic]**
`training/` (PRM_TRAIN + RLAIF), `prm.py` (Null/Heuristic only; RemotePRM is a
stub), and `compaction.py`'s learned gate are all **scaffolds explicitly waiting
on an outcome-reward signal that doesn't exist**. This is architectural debt
posing as roadmap. **Either** commit to closing the loop (C1 eval → reward →
learned PRM / compaction gate) **or** prune the scaffolds. Pick one and say so.

### C3. Verifier depth (smaller than it looks) **[near-term]**
Correction to a common misread: the verifier *is* implemented
(`verifier.py::verify_proposal` / `verify_final`) and *is* wired into the loop
(`agent.py:1071`). The legitimate item is narrower: confirm it runs **default-on
across goal types** (not just coding mode) and characterize **revision-loop
depth**. A roadmap line, not a rewrite.

> **Resolved (June 2026):** default-on **confirmed**. `verify_final` runs on
> every orchestrator depth-0 FINAL regardless of goal type
> (`agent.py:1155–1342`), gated only on role / depth / once-per-goal — coding
> mode merely swaps in the test-driven verifier when ground-truth tests exist.
> Revision loop is capped at **one** retry (`_verifier_revision_used` /
> `_patch_validated`).

---

## D. Reliability plumbing the breadth hides

### D1. Shared tool-reliability layer **[near-term]**
~80 tools are mostly thin API wrappers with no retry / backoff / rate-limit /
fallback. Add one shared reliability policy (not per-tool) so flaky upstreams
don't sink a long run.

### D2. Cross-goal semantic memory wired into the loop **[near-term]**
Vector stores (Chroma/Qdrant) exist but are **unused by the agent loop**, and
reflexion recall is token-Jaccard (`reflexion.py`) — similar failures with
different wording are missed. Wire a semantic memory path into reflexion + skill
retrieval.

### D3. Close or de-scope session-provider tool-use gaps **[near-term]**
Grok / Gemini / Kimi / ChatGPT-web session providers `raise NotImplementedError`
for tool use (`session_providers/*`). That's a silent capability cliff — either
implement or clearly document the limitation in the wizard.

---

## What to de-prioritize
- The far-future breadth (3D viewers, AR plan-trees, ROS robotics, WebRTC,
  voice-biometric unlock) is speculative relative to A–C.
- The homegrown **ACD spec** likely should yield to A2A (see B3).

---

## Top 6 near-term picks — *updated June 2026*
Picks 1–2 and most of 3 have shipped; 5–6 are partially done. Strikethrough =
landed. The remaining near-term priorities:
1. ~~Durable/resumable execution + checkpoint/rewind (A1).~~ ✅ shipped.
2. ~~Kernel lifecycle hooks as the shield/budget/killswitch chokepoint (A2).~~ ✅ shipped.
3. **MCP elicitation + async tasks (B1)** — output schemas, resources, streamable
   HTTP, and subscriptions already shipped; these two remain and need a design
   for the synchronous stdio loop.
4. **Remote-HTTP MCP *client* transport → then OAuth 2.1 + Registry (B2)** — the
   client is stdio-only today, so the transport is the prerequisite; OAuth
   validation also needs real accounts.
5. **Finish A3:** memory / context-editing abstraction + programmatic tool
   calling (deferred tool loading already shipped, #693).
6. **Finish C1:** τ²-bench / terminal-bench adapters + a firmer
   skill-distillation quality/pruning gate (GAIA harness shipped #687; quality
   gate #396 exists).

---

## Accuracy caveats (verify before turning into roadmap commitments)
- **MCP Sampling / Roots / Logging appear to be on a deprecation path** in a
  forthcoming spec revision — do **not** build on sampling.
- Several ecosystem sources (a mid-2026 MCP spec RC, LangGraph 1.2, terminal-bench
  2.0 scores) **postdate the author's knowledge cutoff**; they were taken from
  primary blogs/docs but the exact versions/dates need re-verification.
- Vendor-reported benchmark numbers are directional (contamination / single-run
  inflation) — run multi-seed and treat as indicative, not absolute.
