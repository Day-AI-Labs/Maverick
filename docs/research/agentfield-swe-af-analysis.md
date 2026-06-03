# AgentField / SWE-AF vs. Maverick — Competitive Analysis

> Deep-research report. Date: 2026-06-03.
> Scope: [agentfield.ai](https://agentfield.ai/) + [docs/learn](https://agentfield.ai/docs/learn),
> [github.com/Agent-Field/agentfield](https://github.com/Agent-Field/agentfield),
> [github.com/Agent-Field/SWE-AF](https://github.com/Agent-Field/SWE-AF), benchmarked against
> Maverick's actual codebase (`packages/maverick-core`, `packages/maverick-shield`).
> Method: 5 parallel web-research angles + 1 codebase ground-truth pass, with adversarial
> verification of load-bearing claims. Findings re-verified against Maverick source before
> publishing (an earlier draft mis-stated two items — see "Corrections" at the end).

## Bottom line

1. **The premise needs correcting.** "AgentField" and "SWE-AF" are not a benchmark and not a
   single competing framework. **AgentField** is an open-source *control plane / backend* for
   deploying agents as governed REST services; its real differentiator is **cryptographic
   identity + a signed audit trail** (a W3C DID per agent — "Kubernetes for agents").
   **SWE-AF** ("Autonomous Fleet") is a *reference application* on top of it — an autonomous
   coding system. Neither is a model, and **"SWE-AF" is not a SWE-bench-style benchmark.**
2. **On the axes that matter for a safe consumer agent, Maverick is ahead or on par** — hard
   budget caps, content/injection safety, sandbox diversity, anti-test-cheating, and
   cheap-model routing are all present in Maverick and largely *absent* in SWE-AF/AgentField.
3. **The genuinely transferable ideas are few and specific** (see "Worth adopting"). The
   single highest-leverage move is **model choice + a real benchmark number**, not more
   orchestration. The strongest external evidence is *skeptical* of multi-agent
   role-simulation for coding — which is an argument for Maverick's shared-context design,
   not SWE-AF's 22-agent pipeline.

---

## What these projects actually are

| | **AgentField** | **SWE-AF** |
|---|---|---|
| Category | Open-source **control plane / "AI backend"** — deploy agents as governed REST endpoints | **Autonomous coding "fleet"** built *on* AgentField |
| Tagline | "Build, deploy, and govern AI agents like APIs" | "Autonomous software-engineering fleet … production-grade PRs" |
| Real differentiator | **W3C DID per agent + signed, verifiable audit chain** | 3-tier escalation loop + git-worktree role fleet |
| Stack | Go control plane (~51%), TS/Python SDKs; decorator model (`@app.reasoner`/`@app.skill`); LiteLLM | ~99.7% Python; runtimes `claude_code` / `open_code` / `codex` |
| Coordination | Service-mesh RPC: `app.call("node.reasoner")` + tag discovery ("no DSL/graph wiring") | Fixed role pipeline, issue DAG (Kahn's algorithm), worktrees |
| Maturity | Launched Dec 10 2025; ~2.1k★; v0.1.88 (2026-06-02); pre-1.0 | Created Feb 2026; ~831★; Apache-2.0; "Public Beta" |

**SWE-AF mechanics** (ground-truthed from `swe_af/execution/schemas.py`): a ~22-agent pipeline —
PM → Architect → Tech Lead → Sprint Planner → Issue Writer (planning); Coder → QA + Reviewer →
Synthesizer → Advisor → Replanner (execution); Merger → Integration Tester → Verifier → PR
(integration). Work runs as an issue DAG, each issue in an isolated git worktree
(`issue/{NN}-{slug}`, `max_concurrent_issues: 3`), under a **three-tier escalation loop**:

- **Inner** = coder retry on QA/review failure (`max_coding_iterations: 5`).
- **Middle** = Retry Advisor (`max_advisor_invocations: 2`), typed verbs
  `retry_modified` / `retry_approach` / `split` / `accept_with_debt` / `escalate_to_replan`.
- **Outer** = Replanner (`max_replans: 2`), verbs `continue` / `modify_dag` / `reduce_scope` /
  `abort`. Crash/ambiguity fallback is `continue` (fail-forward).

Verification is test-gated: post-merge it opens a **real PR and polls GitHub Actions to
conclusion** (`check_ci: true`, `ci_wait_seconds: 1500`), with a CI-fix loop
(`max_ci_fix_cycles: 2`) that **forbids `pytest.skip`/`xfail`/assertion-loosening**.

---

## The headline number is marketing, not science

SWE-AF's README claims **95/100 vs. Claude Code Sonnet 73, Codex o3 62** at **~$6** (MiniMax
M2.5). Do not trust this as a quality claim:

- **n = 1.** A *single* self-authored task — a Node.js to-do CLI — scored on a 100-pt rubric
  SWE-AF wrote (Functional 30 / Structure 20 / Hygiene 20 / Git 15 / Quality 15). Not
  SWE-bench, not third-party, not multi-instance.
- **The gap is a rubric artifact.** The 95-vs-73 delta comes mostly from *Structure / Hygiene /
  Git* points — things a one-shot CLI agent isn't told to optimize. Claude Code Sonnet scored
  30/30 functional and *higher* on Quality. The harness wraps a checklist the baselines weren't
  running.
- **The cheap-cost story is real — but it's the *model*, not SWE-AF.** MiniMax M2.5
  independently scores ~80% on SWE-bench Verified at ~1/20th frontier cost. "Near-frontier
  coding from a cheap open model" holds *with or without* the fleet.

> Confidence note: the exact 2026 SWE-bench Verified leaderboard toplines surfaced by search
> (frontier ~88–94%, MiniMax M2.5 ~80%) are environment-dated and not independently verified
> here. The **direction** — cheap open models are now near-frontier on coding at ~1/20 cost —
> is corroborated across sources and is robust.

---

## Head-to-head: where Maverick stands (verified against source)

| Capability | Maverick (file evidence) | SWE-AF / AgentField | Verdict |
|---|---|---|---|
| **Hard $/token/wall-clock budget caps** | `Budget.check()` enforced atomically; synthesis reserve; per-provider cache pricing (`budget.py:124,286`) | Cost only *tracked*, never capped; caps are iteration/time counters | ✅ **Maverick ahead** |
| **Content / injection safety** | Shield scans input/tool-call/output, secret redaction, fail-open (`maverick_shield/guard.py`, `agent.py:500-571`) | None; `permission_mode` defaults to `""`; governance ≠ content safety | ✅ **Maverick ahead** |
| **Anti-test-cheating** | `defensive_validate()` hard-blocks edits to `tests/`/`test_*.py`/`conftest.py`/FAIL_TO_PASS paths + lockfiles, plus gold-patch overlap detector (`coding_mode.py:775`, wired `agent.py:1076`) | Prompt-rule only ("don't skip/xfail") | ✅ **Maverick ahead** |
| **Sandbox isolation** | 7 backends (Local/Docker/Podman/Devcontainer/K8s/Firecracker/SSH) (`sandbox/__init__.py`) | Only Codex's inherited bubblewrap; other runtimes none | ✅ **Maverick ahead** |
| **Cheap-model routing** | `MODEL_PRICES` registers DeepSeek/Kimi/Gemini-Flash/Qwen; `cost_router` tiers + per-role assignment (`llm.py`, `cost_router.py`) | Per-role cascade (`runtime default < models.default < models.<role>`) | ✅ **On par / slight edge** |
| **Per-role model selection** | `model_for_role()` 6-level resolution (`llm.py:157`) | Role→model map | 🟰 **On par** |
| **Git worktrees** | Yes — for *safe patch application* (`agent.py:330-375`) | Yes — for *parallel isolation* | 🟰 **Different purpose** |
| **Real SWE-bench harness** | Yes, with **test-driven** ground-truth grading (`benchmarks/swe_bench.py`, `agent.py:1165-1283`) | None — only the toy rubric | ✅ **Maverick ahead** |
| **Risk-proportional verification** | Uniform verifier depth (no skip for trivial) | `needs_deeper_qa` routes 2-call vs 4-call path per issue | ❌ **Maverick lacking** |
| **Live-CI terminal gate** | LLM-panel verifier off-benchmark; no real-PR/CI poll | Opens real PR, polls GitHub Actions to conclusion | ❌ **Maverick lacking** |
| **Act on swarm disagreement** | Entropy *measured* and posted; acting on it is a coded TODO (`spawn.py` "deferred follow-up") | Typed advisor/replanner act on failure | ⚠️ **Maverick partial** |
| **Honest debt in user-facing output** | Low confidence/critique carried in `AgentResult`, not surfaced in `final` text | `accept_with_debt` → debt notes in PR body | ⚠️ **Maverick partial** |
| **Full-build checkpoint/resume** | Depth-0 only (`checkpoint.py`) | `.artifacts/{plan,execution,verification}` + `resume_build` | ⚠️ **SWE-AF edge** |
| **Cryptographic audit trail** | Heavy instrumentation; no signed chain | DID + verifiable credentials per call | ⚠️ **AgentField edge (enterprise-only)** |

---

## What's genuinely worth adopting

After verifying against source, the anti-cheat and cheap-routing recs from the first draft are
**already implemented**. The real, remaining candidates:

**Highest value (consumer-facing honesty + reliability):**

1. **Surface "couldn't fully verify / known limitations" in the user-facing answer.** Today,
   when the verifier rejects after the one allowed revision, Maverick accepts the second attempt
   *regardless* (`agent.py:1323-1334`, `1349-1362`) and the low confidence/critique live only in
   `AgentResult`, not in the answer the user reads. Borrow SWE-AF's `accept_with_debt` idea:
   attach an honest caveat when confidence is low. (Caveat: in coding mode `final` is a patch —
   the note must not corrupt it; surface via the result/critique channel there.)
2. **Act on the swarm-disagreement signal you already compute.** `spawn_swarm` measures answer
   entropy across siblings and explicitly defers acting on it. Closing that TODO — escalate /
   re-fan-out / lower confidence when entropy is high — is the natural next step and needs no
   new infrastructure.

**Medium value (cost + ground truth):**

3. **Register MiniMax M2.5 (and peer open near-frontier models) so the research's cost lever is
   reachable.** The routing infra exists; the specific cheap model the field is excited about
   isn't in `MODEL_PRICES`/`cost_router`. Proper add = price entry + provider/OpenRouter path +
   router tier + wizard toggle (per `CLAUDE.md` rules 5–6).
4. **Risk-proportional verification.** Skip the verifier panel for trivially-safe tasks; reserve
   deeper checks for risky ones (SWE-AF's `needs_deeper_qa`). Trade-off: skipping verification
   reduces safety — gate it conservatively.
5. **Live-CI verifier mode for real repos** (not just SWE-bench): open a PR, poll Actions to
   conclusion, feed failures into the existing bounded fix loop. Stronger ground truth than an
   LLM judge.
6. **Extend checkpoint/resume below depth-0** so long swarm runs survive crashes like SWE-AF's
   `resume_build`.

**Conditional / strategic:**

7. **Parallel-coding worktrees + semantic merge** — *only* for truly independent subtasks.
   Maverick currently serializes coder children via a workdir lock, sidestepping merges. The
   evidence (below) says parallel code editing is where multi-agent most often fails; adopt
   narrowly, gated by dependency analysis.
8. **Signed audit trail** (AgentField's DID idea) — skip for consumers; revisit only for a
   future enterprise/regulated tier.

---

## The strategic caveat (most important finding)

Maverick is positioned as a **recursive multi-agent swarm**. The strongest external evidence is
*skeptical of multi-agent role-simulation for coding specifically*:

- **Cognition / Devin — "Don't Build Multi-Agents":** parallel sub-agents editing code fail from
  context fragmentation (conflicting implicit decisions). Prescribes single-threaded,
  context-sharing agents. <https://cognition.ai/blog/dont-build-multi-agents>
- **Anthropic's** multi-agent win (+90% over single Opus) is on a **research/breadth** eval at
  ~15× tokens; the post *explicitly* says coding has "fewer truly parallelizable tasks than
  research." Even the leading pro-multi-agent result carves coding out.
  <https://www.anthropic.com/engineering/multi-agent-research-system>
- **MAST** (NeurIPS 2025; 1600+ traces; 7 frameworks): failures dominated by *specification*
  (~42%) and *coordination* (~37%) — the overhead multi-agent itself introduces.
  <https://arxiv.org/abs/2503.13657>
- **Routing economics are real and literature-backed** (RouteLLM: route ~85% of queries to
  cheap models, keep ~95% of frontier quality). <https://arxiv.org/pdf/2410.10347>

**Implication — good news for Maverick's design.** Maverick is a *single recursive agent with
shared context* (one `SwarmContext`, one blackboard, one budget across the tree; `swarm.py:54`),
not a fixed 22-agent assembly line passing serialized state like SWE-AF. That is much closer to
the "shared context, not shared state" pattern the failure literature endorses. So:

- **Do not copy SWE-AF's heavyweight role pipeline.** Lean into shared-context spawning; reserve
  fan-out for genuinely independent subtasks.
- **Use the SWE-bench harness you already have (and SWE-AF lacks) to publish a real, comparable
  number.** That number is the credibility SWE-AF is missing, and the only way to know whether
  the swarm helps or merely costs tokens.

---

## Confidence & caveats

- **High confidence** (code-level or multi-source): Maverick's architecture and the
  `defensive_validate` / budget / shield / routing facts (read from source); SWE-AF's loop/config
  (`schemas.py`); AgentField = control plane with DID/audit (GitHub + SiliconANGLE); the
  multi-agent-for-coding skepticism (4 independent sources); RouteLLM economics.
- **Flagged / lower confidence:** all SWE-AF performance numbers are vendor self-reports (n=1);
  exact 2026 leaderboard figures and a few arXiv IDs are environment-dated (June 2026) and not
  independently verifiable — only the *directional* claims were relied on. AgentField's homepage
  enterprise-logo claims are unverified marketing.

## Corrections to the first draft

The initial synthesis (based on an architecture-only codebase scan) wrongly listed two items as
Maverick gaps. Re-reading source corrected them:

- **Anti-test-cheating is NOT missing.** `defensive_validate()` (`coding_mode.py:775`) already
  hard-blocks test/lockfile edits and runs a gold-patch overlap cheating detector. Maverick is
  *ahead* of SWE-AF here.
- **Cheap-model routing is NOT missing.** `MODEL_PRICES` + `cost_router` already cover
  DeepSeek/Kimi/Gemini-Flash/Qwen with per-role tiers. Only MiniMax M2.5 specifically is
  unregistered.

## Sources

- AgentField: <https://agentfield.ai/>, <https://github.com/Agent-Field/agentfield>,
  <https://siliconangle.com/2025/12/10/agentfield-tries-fix-agentic-ais-identity-crisis-cryptographic-ids-kubernetes-style-orchestration/>
- SWE-AF: <https://github.com/Agent-Field/SWE-AF> (README + `docs/ARCHITECTURE.md` +
  `swe_af/execution/schemas.py`)
- Multi-agent evidence: Cognition, Anthropic, MAST (`arXiv:2503.13657`), RouteLLM
  (`arXiv:2410.10347`)
- Worktree parallelism: <https://code.claude.com/docs/en/worktrees>
- Cheap-model datapoint: <https://openrouter.ai/minimax/minimax-m2.5>
