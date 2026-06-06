# Maverick — Second-Pass Analysis: AgentField Delta, Enterprise Readiness, and the "Agentic OS" Question

> Deep-research report #2. Date: ~2026-06-06 (≈1 week after the first analysis, 2026-06-03).
> Method: 6 parallel agents (5 web angles + 1 codebase audit), adversarial verification of
> load-bearing claims, re-grounded against Maverick source. Where this corrects the first
> report, it says so explicitly.

## Bottom line (three verdicts)

1. **AgentField shipped its moat.** The governance layer that was "aspirational" a week ago — per-agent W3C DIDs + Ed25519-signed verifiable-credential audit + tag-based access policies — is now **real, tested code** (v0.1.89 stable; integration test with 20+ functions). Their commercial/enterprise *go-to-market*, however, is still embryonic (no pricing, no trust portal, no certs, no verifiable customers). They are aiming squarely at the enterprise's #1 pain.
2. **Maverick is far more enterprise-ready than its own framing implies** — and the first report undersold it. Maverick already has tamper-evident **signed audit** (Ed25519 Merkle chain), **tool-level RBAC**, **OpenTelemetry + Prometheus**, **HITL consent**, **signed skills**, and **GDPR erasure**. The genuine gaps are narrow: **identity/SSO, multi-tenancy, and quotas/chargeback**.
3. **"Agentic Operating System" — adopt the architecture, reject the branding.** The *term* is saturating fast (5+ vendor launches in 2026, Microsoft backlash, "means everything and nothing"). But the *substance* is a real wedge: Maverick already implements more agentic-OS primitives than the canonical academic kernel (AIOS), including the ones AIOS leaves unowned (budgets, sandboxing, audit). **Don't rename the product "Agentic OS"; do organize the roadmap around owning the OS primitives others skip — starting with the one that is simultaneously the enterprise gap: identity.**

---

## Part 1 — Week-over-week delta (AgentField / SWE-AF)

**The headline: governance moved from roadmap to shipped.** The four features flagged "aspirational" in report #1 are now backed by real code, verified directly:

- Per-agent **W3C DIDs** (`did:key` Ed25519 + `did:web`), 3-tier hierarchy, AES-256-GCM keystore.
- Per-execution **Verifiable Credentials**, Ed25519-signed, with an **offline verify CLI** (`af vc verify audit.json`).
- **Tag-based ALLOW/DENY access policies** with wildcard eval + replay-attack/timestamp middleware.
- **HITL** durable `app.pause()` now a documented first-class SDK feature.

Evidence is a shipped integration test — `control-plane/internal/vc_authorization_integration_test.go` (5 phases, 20+ functions, incl. a registration regression test) — read from raw GitHub, not marketing. [[delta]](https://github.com/Agent-Field/agentfield) [[code]](https://raw.githubusercontent.com/Agent-Field/agentfield/main/control-plane/internal/vc_authorization_integration_test.go)

Other deltas:
- **Releases:** v0.1.89 stable (2026-06-04); v0.1.90-rc.1/rc.2 (rc.2 = 2026-06-06). Changelog is minor (dep bumps, a security fix "authorize execution note reads").
- **Traction:** agentfield ~2,107★ (flat) / 335 forks (up); SWE-AF 836★ / 133 forks. ~32 commits/week.
- **SWE-AF is static** — last pushed 2026-06-01 (before the window). Same 3-tier loop, same self-reported todo-CLI benchmark, **still no independent SWE-bench entry**.
- **A "userland" is forming:** the org now has 12 repos, including apps built *on* the platform — `sec-af`, `pr-af`, `af-deep-research`, `reels-af`, `plandb`. (Platform + applications — relevant to Part 3.)
- **No funding/pricing news.** Pre-seed (Panache, Brightspark); amount undisclosed.

**Do report #1's recommendations still hold?** Yes. Two shipped (honesty caveat, risk-proportional verification). The cheap-model and live-CI-verifier recs are unaffected. The one update: AgentField's identity/audit is no longer a "future maybe" — it's a shipped differentiator, which raises the priority of Maverick's identity gap (Part 2/3).

---

## Part 2 — Enterprise readiness

### What enterprises actually require (2026)

The #1 blocker to production agents is **governance/identity, not capability**. Across multiple 2026 surveys (Okta, CSA/Zenity, Gravitee, McKinsey — all directionally consistent though several are vendor-interested), agent **identity** is the sharpest gap: only ~22% treat agents as identity-bearing; ~53% have had agents exceed intended permissions. A *second*, distinct production blocker is **eval/observability**.

| Requirement | 2026 status | Maverick today |
|---|---|---|
| SSO (SAML/OIDC), SCIM | **Table-stakes** | ❌ absent (channel/user-id strings only) |
| RBAC | **Table-stakes** | ⚠️ tool-level only (`safety/tool_acl.py`), not user/resource-level |
| Audit logs (retention, SIEM export) | **Table-stakes** | ✅ append-only NDJSON + **Ed25519 Merkle chain** (`audit/signing.py`) |
| SOC 2 Type II | **Table-stakes** | ❌ no attestation (process, not code) |
| Multi-tenancy / tenant isolation | **Table-stakes** | ❌ single shared world model |
| Secrets mgmt, PII masking | **Table-stakes** | ⚠️ secret redaction in audit; no per-tenant KMS |
| Guardrails / content safety | **Table-stakes** | ✅ Agent Shield (injection/exfil, fail-open) |
| HITL approval | **Table-stakes** | ✅ consent gating + MCP elicitation (`safety/consent.py`) |
| Observability / tracing | **Table-stakes**; OTel-native = differentiator | ✅ **OpenTelemetry + Prometheus** (opt-in) + dashboard |
| **Agent-native identity / IAM** | **Differentiator → fast becoming table-stakes** | ❌ **the core gap** |
| **Tamper-evident action-level audit** | **Differentiator** | ✅ already have it (Merkle-chained) |
| **Eval-gated release** | **Differentiator** | ⚠️ SWE-bench + tau2 harnesses exist; not wired as a release gate |
| **On-prem / air-gapped** | **Strong differentiator (rare)** | ✅ self-host default, 7 sandboxes, local models |
| **Quotas / chargeback** | **Differentiator** | ❌ budget is per-run only |
| Cost governance (per-run) | — | ✅ hard `Budget.check()` |

### The corrected gap list

Report #1 implied Maverick was broadly behind on enterprise/governance and that signed audit was AgentField's edge. **The code says otherwise.** Maverick already holds several *differentiators* (signed tamper-evident audit, air-gapped self-host, OTel, content safety, HITL). The genuine, narrow gaps are:

1. **Identity / auth** — no SSO/OIDC/SAML, no per-agent identity. *(Industry #1 gap; AgentField's exact wedge.)*
2. **Multi-tenancy** — one shared world model; no tenant isolation.
3. **Quotas / chargeback** — aggregate/per-principal limits (today: per-run only).
4. **SSO/SCIM + SOC 2 Type II** — entry tickets (compliance process, not novel engineering).
5. **Eval-gated release** — turn the existing SWE-bench/tau2 harnesses into a CI gate.

### Maverick vs AgentField (enterprise)

They are converging from **opposite ends**. AgentField is governance-first infra that shipped identity/audit but is a shallow *agent* (SWE-AF is a thin coding demo, no real benchmark). Maverick is a capable agent (recursive swarm, budgets, sandboxes, shield, SWE-bench harness) that lacks *identity*. The two product roadmaps meet at exactly one primitive: **per-agent identity + capabilities**. Whoever owns capable-agent **and** governed-identity first wins the enterprise wedge.

---

## Part 3 — The "Agentic Operating System" question

### The term is saturating — do not brand it

"Agentic OS"/"Agent OS" was launched as a category claim by **5+ vendors in 2026 alone** — Fiserv (banking), Amdocs (telecom), Legora (legal), PubMatic (adtech), Infobip (CX) — almost all vertical marketing over orchestration layers. Microsoft's "Windows is evolving into an agentic OS" (Nov 2025) drew a **public backlash**. Industry commentary openly calls it a term that "means everything and nothing." Even believers avoid the literal name (Salesforce uses OS *rhetoric* but ships "Agentforce"; Microsoft brands Agent 365 a "control plane"). Substantive usage is concentrated in academia (AIOS, MemGPT/Letta) and a few infra products (Agno's AgentOS, Rivet, /dev/agents).

**Verdict on branding:** picking "Agentic Operating System" as the product name means fighting Microsoft/Salesforce/ServiceNow/Fiserv for a generic, backlash-tainted term. Reject it as a name.

### The architecture is a real wedge — adopt it internally

Treat the OS analogy rigorously (per AIOS, COLM 2025 — the only project with a real agent "kernel"). The decisive finding: **AIOS explicitly leaves the hardest primitives unowned** — no token/compute **budgets/quotas**, no **inter-agent IPC**, no **tool sandboxing**, only coarse permissions. Those unclaimed primitives are exactly where Maverick is already strong.

| OS primitive | Agent analog | Maverick today (file) | AIOS (canonical kernel) |
|---|---|---|---|
| Kernel / scheduler | dispatch & schedule agents | recursive swarm, spawn caps (64), parallel tool exec, cron (`swarm.py`,`scheduler.py`) | FIFO/RR only |
| Processes / isolation | agents + sandboxing | **7 sandbox backends** (`sandbox/`) | ❌ no tool sandbox |
| Syscalls / drivers | tools, providers, channels | 80+ tools, 10+ providers, MCP (stdio+**HTTP**), 10 channels | LLM syscall + adapters |
| IPC | inter-agent comms | blackboard + spawn handoffs (in-proc) | ❌ none |
| Memory mgmt | context=RAM, long-term=disk | compaction + world model + **cross-session memory** (`tools/memory.py`) | K-LRU evict |
| Permissions / capabilities | per-agent access | tool ACLs + risk ceilings + consent (`safety/`) | coarse hashmap |
| Filesystem / state | persistent state | world model (SQLite/FTS5) + checkpoints | storage mgr |
| Package manager | installable skills/tools | **signed** skills + MCP servers (`skills.py`) | tool manager |
| **Budgets / quotas** | cost as managed resource | **hard `Budget.check()`** (per-run) | ❌ **unowned** |
| **Audit / governance** | tamper-evident log | **Ed25519 Merkle chain** + GDPR erase (`audit/`) | access mgr only |
| Observability | tracing / metrics | **OTel + Prometheus** + dashboard | — |
| **Identity** | users/agents as principals | ❌ **absent** | coarse privilege groups |

**The analytical punchline:** Maverick already implements *more* of the agentic-OS primitive set than AIOS — and is ahead specifically on the primitives the field leaves unowned (budgets, sandboxing, signed audit). The "agentic OS" architecture is therefore substantively true of Maverick, not aspirational.

### The convergence (the single most important insight)

The **one missing OS primitive (identity/users/capabilities)** is the **same thing** as the **#1 enterprise gap** and the **same thing** as AgentField's shipped wedge. One investment resolves all three. And Maverick already has the cryptographic substrate for it: **Ed25519 signing is already in the codebase** (audit chain + skill signing) — so per-agent identity + capability tokens are a *reuse*, not a from-scratch build.

---

## Recommendations (prioritized)

**P0 — the convergence play: an identity + capability layer.**
Per-principal identity for both human users (OIDC/SSO) and agents (per-agent keypair → signed capability tokens scoping tool/resource access). Reuse the existing Ed25519 infra (`audit/signing.py`, `skills.py`). This single layer closes the enterprise #1 gap, completes the agentic-OS story, and directly answers AgentField's DID/VC moat. Surface it in the wizard (rule 6).

**P1 — multi-tenancy.** `tenant_id` partitioning across world model, memory, audit, and budget so Maverick can be deployed for teams/SaaS, not just one user.

**P2 — quotas/chargeback.** Extend `Budget` from per-run to aggregate per-principal/tenant/time-window caps with usage accounting (the AIOS-unowned "cost as a managed resource" primitive).

**P3 — eval-gated release.** Wire the existing SWE-bench + tau2 harnesses into CI as a regression gate (the top *production* blocker per the surveys; cheap given the harnesses already exist).

**P4 — compliance entry tickets.** SSO/SCIM connectors + start the SOC 2 Type II clock. Necessary, not differentiating.

**Positioning.** Do **not** brand "Agentic OS." Lead with substance: *the governed agent runtime* — a recursive multi-agent swarm with the primitives others skip (hard budgets, sandboxing, signed audit, capabilities, content shield). Use "agentic OS" only as an internal architectural North Star.

---

## Confidence & caveats

- **High confidence (code-verified):** AgentField governance shipped (integration test read from raw GitHub); Maverick's existing primitives (file:line from source audit); AIOS leaves budgets/IPC/sandboxing unowned (arXiv 2403.16971, COLM 2025).
- **High confidence (multi-source):** "Agentic OS" term saturation (5+ named vendor launches + Microsoft backlash + explicit skepticism); AgentField commercial GTM embryonic (verified 404s on /pricing and /security).
- **Directional only (vendor-interested / secondary):** the exact enterprise survey percentages (33% governance-ready, 53% scope violations, 88% pilots fail) — Okta/Gravitee/CSA have a stake in "governance is the problem," and some figures are secondary aggregators. The *direction* (identity/governance is the #1 gap) is robust; treat specific numbers as indicative.
- **Single-sourced:** AgentField star/fork counts (GitHub search API, one path). SWE-AF's 95/100 remains an unverified self-report.
- **Analytical (mine, well-grounded):** "Maverick implements more OS primitives than AIOS" follows from the code audit + the AIOS paper; "the three problems are one problem (identity)" is a synthesis, not a sourced fact.

## Sources

- AgentField: <https://github.com/Agent-Field/agentfield> (+ `control-plane/internal/vc_authorization_integration_test.go`, releases), <https://agentfield.ai/>, <https://pypi.org/project/agentfield/>
- Enterprise: <https://www.okta.com/newsroom/articles/ai-agents-at-work-2026-agentic-enterprise-security/>, <https://cloudsecurityalliance.org/press-releases/2026/04/16/more-than-half-of-organizations-experience-ai-agent-scope-violations-cloud-security-alliance-study-finds>, <https://www.gravitee.io/blog/state-of-ai-agent-security-2026-report-when-adoption-outpaces-control>, <https://workos.com/blog/enterprise-readiness-checklist-2026>, <https://www.langchain.com/blog/langgraph-platform-ga>, <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- Agentic OS: <https://arxiv.org/abs/2403.16971> (AIOS), <https://arxiv.org/abs/2310.08560> (MemGPT), <https://modelcontextprotocol.io/specification/2025-11-25>, <https://docs.agno.com/agent-os/introduction>, <https://www.tomshardware.com/software/windows/top-microsoft-execs-boast-about-windows-evolving-into-an-agentic-os-provokes-furious-backlash>, <https://datasciencedojo.com/blog/agentic-os-architecture/>
