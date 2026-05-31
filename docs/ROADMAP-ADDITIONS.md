# Roadmap Additions — Gap Analysis (May 2026)

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

### B1. Modernize the MCP *server* **[near-term]**
`packages/maverick-mcp` is hand-rolled, protocol `2024-11-05`, 8 tools, "no SDK
dep." The **entire cross-language strategy** ("drive Maverick over MCP") rides on
this surface, and it's stale. Adopt the current spec: structured **output
schemas**, **resources / prompts**, **streamable HTTP** transport, and
**elicitation** — the last maps cleanly onto the shield's consent UI (form mode +
URL mode for secrets that must never enter model context).

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

## Top 6 near-term picks
1. Durable/resumable execution + checkpoint/rewind (A1).
2. Kernel lifecycle hooks as the shield/budget/killswitch chokepoint (A2).
3. MCP server modernization: output schemas, resources, streamable HTTP,
   elicitation (B1).
4. MCP client OAuth 2.1 + Registry + allowlist governance (B2).
5. Provider-neutral memory / context-editing / tool-search layer (A3).
6. Eval harness (GAIA/τ²-bench/terminal-bench) + skill-distillation quality
   gate (C1).

---

## Accuracy caveats (verify before turning into roadmap commitments)
- **MCP Sampling / Roots / Logging appear to be on a deprecation path** in a
  forthcoming spec revision — do **not** build on sampling.
- Several ecosystem sources (a mid-2026 MCP spec RC, LangGraph 1.2, terminal-bench
  2.0 scores) **postdate the author's knowledge cutoff**; they were taken from
  primary blogs/docs but the exact versions/dates need re-verification.
- Vendor-reported benchmark numbers are directional (contamination / single-run
  inflation) — run multi-seed and treat as indicative, not absolute.
