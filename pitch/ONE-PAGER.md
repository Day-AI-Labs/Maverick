# Lightwork — One-Pager

> **Lightwork, by Daybreak Labs** — the agent workforce a regulated enterprise can actually deploy.
> Self-hostable. Tamper-evident. Provably improving.
> Christopher Day, Founder · `[FILL: email]` · `[FILL: data-room link]` · 2026

---

**The problem.** Every enterprise wants an AI agent workforce; almost none can
deploy one where it matters. In regulated, high-stakes work the blocker isn't
capability — it's **governance, auditability, and trust.** When the CISO,
compliance officer, and general counsel enter the room, the pilot dies: nobody
can prove the agent stayed in policy, prove it couldn't exfiltrate data, or
prove it won't quietly get worse. Today's options force a bad trade — **hosted
black boxes** you can't run on your own data, or **ungoverned frameworks** you
have to secure yourself.

**The solution.** Lightwork is a governed agent **runtime** — not a chatbot, not
a framework. A recursive multi-agent swarm where **every single action passes
one chokepoint:** capability check → governance policy (allow / deny /
require-human) → safety shield → hard budget → **tamper-evident, signed audit
log.** It **self-hosts or air-gaps** — runs on the customer's data, in their
environment, with no required egress, so even a successful prompt injection
can't move data out. And it ships a **closed, audited learning loop** — a
workforce you can prove is improving, not a static model.

**Why now.** Enterprise agentic AI is moving from pilots to budget but stalling
on governance. Regulation (EU AI Act, HIPAA, SOX, GLBA) is making "ungoverned
agent" a non-starter. Gartner sizes AI-governance platforms at ~$492M (2026) → $1B+ by 2030, with AI regulation reaching 75% of economies by then. And the 2026 capital market has
repriced to **reward defensible IP and punish thin AI wrappers.**

**What's built (alpha, installable today — every number verifiable):**
- **~310K LOC** across **8 PyPI packages**; FastAPI dashboard; native installers
  for Windows / macOS / Linux; an MCP server; a GitHub Action.
- **Self-host or air-gap** — runs in the customer's VPC or fully offline; no required egress.
- **1,118 least-privilege specialist packs across 26 suites** —
  `maverick domains-lint` → **0 errors, 0 warnings.**
- **The product proves its own guarantees:** `maverick proof-pack` emits an
  **Ed25519-signed evidence bundle** (governance guarantees + reliability cert +
  performance SLA + shield results), verifiable offline.
- **A governance demo that runs in front of you:** a finance specialist boots
  *sealed*, a $60k wire is **DENIED**, a $6k release **REQUIRES A HUMAN**, a
  runaway loop is **CAPPED**, and altering one audited row is **caught** —
  leaving a tamper-evident receipt.
- **The enterprise loop is closed:** a goal's result renders as a **typed
  deliverable** → a per-role **inbox** → a human **certifies** it → it routes
  into the system of record (Salesforce / ServiceNow), signed and audited.

**The moat (three reinforcing layers, all audited):** (1) governance bound to
every action — attenuate-only capability tokens, policy engine, egress lock, a
signed hash-chained audit log with offline verification; (2) a snapshot-/
rollback-able **provable-learning loop** where every causal guardrail must
survive a **placebo test** before it changes behavior; (3) the **1,118-pack
governed library.** None of it is a prompt over an API — it's deep
infrastructure a competitor doesn't replicate in a quarter and an incumbent's
hosted product can't air-gap into a bank.

**Market & wedge.** Bottom-up: ~10,000 US regulated financial institutions; 100 customers at a ~$250k ACV ≈ $25M ARR from the BFSI beachhead alone (Gartner sizes AI-governance platforms at $1B+ by 2030). **Beachhead: BFSI / finance**
(highest regulatory pain, clearest ROI; the finance suite already declares ~29
governed deliverables across 11 roles). **Second wedge: tax-prep for CPA firms**
(a deterministic, citation-backed docs → 1040 + state-return pipeline with a
signed tax-law update channel). 26 suites already built for land-and-expand.

**Go-to-market.** Two motions: **direct** — 2–3 BFSI design partners → paid
pilot → expand across suites; and an **overlay wedge** — *"bring your existing
Agentforce / Copilot / LangChain agents under Lightwork governance"* — the
easiest enterprise entry and a natural acquisition story for a GRC / ServiceNow
buyer.

**Competition.** We don't compete on the runtime (a commoditizing race). Sierra
($15.8B) is hosted CX agents — can't air-gap. Cognition is coding. LangChain is
ungoverned plumbing. The incumbents have policy but no agent-native governed
runtime. **Nobody owns "governed, self-hostable, provably-improving agent
workforce for regulated work."**

**Traction.** `[FILL: e.g. "2 BFSI design partners in conversation; 1 signed
LOI; pre-revenue."]`

**Team.** **Christopher Day**, Founder — `[FILL: one-line credibility; the unfair insight / access; any co-founders / advisors.]`

**The ask.** Raising **`[FILL: $X]`** at **`[FILL: $Y pre-money]`** (per Carta, the 2025–26 median AI seed priced at ~$19M pre-money for ~20% dilution — about a $4.5M round; defensible IP commands the premium end). **Use of funds (12–18 mo):** land 3 design
partners live, SOC 2 Type I, first paid ARR, 2 eng hires — converting a built,
defensible asset into a revenue-generating company and a fundable Series A.
