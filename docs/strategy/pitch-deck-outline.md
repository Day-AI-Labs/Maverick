# Pitch-Deck Outline

> 12 core slides + appendix, derived from [`investor-narrative.md`](./investor-narrative.md).
> One idea per slide; the deck is a spine, the narrative is the script. **[FILL IN]**
> = founder-supplied facts; **[verify]** = re-check before external use.

---

**1 · Title**
Maverick — *the self-hostable, governed agent runtime + control plane.*
Sub: "Run autonomous agents on regulated work — and prove what they did."
**[FILL IN]** logo, one-line tagline, contact.

**2 · The problem**
Enterprises are deploying agents that *act* — move money, data, workflows. Five
questions block production: **who owns it, what can it reach, what did it do, why,
can you prove it?** Today's answer: editable logs and standing permissions. Make
the room feel the risk (one concrete "agent did the wrong thing" vignette).

**3 · Why now**
Agents leaving demos → production · a new class of *non-deterministic privileged
actor* · security/legal/audit now in the room · EU AI Act + model-risk rules turn
"we logged it" into "produce tamper-evident evidence" · incumbents validating the
category from both ends **[verify]**. *The window is a neutral, self-hostable control point.*

**4 · What we are**
**Run the agents AND govern them — self-hosted, integrated.** Most of the market
does *either* runtime *or* governance, hosted. One diagram: oversight control
plane (every action flows through it) → fleets → compliance engine, in the
customer's boundary.

**5 · Demo (the heart)**
Live or 90-sec video: agent runs a vendor payment → hits "Pay $48,200" → Maverick
**gates that one action** → human **approves** → **sealed before/after evidence**
→ **/replay** with "chain verified ✓" → **export evidence packet** → **`maverick-verify-audit`**
proves it with no trust in us. *End on the verified evidence, not a chat box.*
(Script: [`flagship-demo-script.md`](./flagship-demo-script.md).)

**6 · Why incumbents don't cover it**
Four-cluster map (1 slide): frameworks *build* agents · hyperscaler platforms
govern *their* walled garden, can't self-host/air-gap · AI gateways stop at model
traffic · GRC tools govern *company* controls, not runtime behavior. Maverick spans
them, in-boundary. (Detail: [`competitive-landscape.md`](./competitive-landscape.md).)

**7 · It's already real (proof)**
Add to the proof logo-grid / appendix A2: **roster-wide governance invariants** (six invariants — tool-reachability, autonomy dial, capability attenuation, compartment isolation, hard refusals, budget caps — verified across all 2,020 packs, fault-injected at 1,000,000 iterations with non-vacuity controls + hostile-argument fuzzing of every connector/tool) and **primary-source data grounding** (37 read-only public-data connectors auto-granted per analyst pack, ON by default with a kill-switch + wizard step). Both are shipped and tested, and both strengthen 'can they build it?' and the governance moat.
Most startups here have a demo; we have a **governed runtime + cryptographic flight
recorder**, ~9,300 tests, a **standalone external verifier**. Logo-grid of the
shipped primitives: signed audit · capabilities · approval gate · replay/evidence ·
trust graph · discovery · simulation · enterprise fail-closed · self-host. *De-risks "can they build it?" — they did.*

**8 · The moat**
**Durable moat = self-host** (data residency / air-gap / "evidence in *our*
environment" — hyperscalers structurally can't). Plus: designed-in evidence graph ·
attenuating capabilities · pre-action simulation + replay · **externally verifiable**
(no trust in us) · switching cost from packs + learning + Operating Record.

**9 · Wedge & ICP**
One buyer, one workflow. Lead with **governance + audit + containment** for a
**regulated ops + security** buyer (fintech / insurance / healthcare ops / secops),
packs as use-case proof — *not* "2,020 agents." The benchmark
([`benchmark-plan.md`](./benchmark-plan.md)) is the proof artifact.

**10 · GTM & milestones**
Next 2 quarters: 3 lighthouse design partners (1 paid) · the flagship demo · SOC 2
Type I + scoped pentest · the safety-vs-completion benchmark · 1 ROI metric + case
study. **[FILL IN]** current pipeline/LOIs/usage.

**11 · Team**
**[FILL IN]** — why this team wins a security-control-point category (lead with
security + enterprise-distribution credibility, relevant prior wins).

**12 · The ask**
Raising **[FILL IN $ / stage]** → convert 3 design partners into 2–3 paying
lighthouse logos + a defensible benchmark in ~2 quarters. Use of funds:
design-partner delivery · SOC 2 + pentest · benchmark · 2–3 GTM/forward-deployed hires.

---

## Appendix (have ready, don't present unless asked)
- **A1 Architecture** — the three-layer control plane + self-host topology.
- **A2 Security & trust** — threat model, signed-audit + external verifier, enterprise mode, RBAC/OIDC/tenancy (point to `docs/enterprise/diligence.md`).
- **A3 Benchmark** — the safety–utility frontier chart + scorecard.
- **A4 Pricing hypothesis** — **[FILL IN]** packaging/ACV bands.
- **A5 Competitive deep-dive** — the five camps + objection-handling.
- **A6 Roadmap** — remote/sandboxed computer-use desktop, multi-tenant SaaS, deeper compliance packs.

## Design notes
- One idea per slide; the demo (5) and proof (7) carry the deck — rehearse those.
- Every product claim is verifiable in the repo; don't overstate traction —
  lead with the moat + the proof, fill real traction into slide 10 as it lands.
- Keep `[verify]` competitor facts current; the space moves monthly.
