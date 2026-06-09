# Moat & acquisition thesis

> Working strategy note, not a contract. Pairs with
> [Competitive landscape](competitive-landscape.md) (where we compete) — this
> doc is *why we're defensible* and *who buys us*. Re-verify external specifics
> before quoting them.

## The blunt version

Most of what people call a "moat" in agents isn't one. The swarm is
commoditized (LangGraph, CrewAI, AutoGen/AG2, OpenClaw, Hermes). The model is
**rented** — zero moat and our biggest dependency risk. Prompts and loop designs
are copyable in a weekend. Even the shield's *rules* are copyable. A pitch of
"we have a really good agent loop" is an acqui-hire, not an acquisition.

The defensible core is the one thing that **compounds with install base and
can't be reconstructed without it**: the evaluator + the verified-trajectory
data asset.

## The moat: evaluator + verified-trajectory data engine

Everything compounds off the donation selector (`maverick.donation.should_donate`):
the system keeps only trajectories where the swarm explored (high disagreement)
**and** a trusted, cross-family verifier confirmed the answer (high confidence)
**and** the outcome succeeded. That asset has three properties an acquirer pays
for:

1. **It compounds with install base.** Every governed run that clears the
   evaluator gate adds a labeled, verified example. A competitor with a better
   loop but no install base cannot reproduce it.
2. **It's domain-specific where the money is.** ~100 regulated-vertical packs
   (`domains/finance_*`, `legal_*`, `hr_*`, `itgrc_*`). A verified-trajectory
   corpus for "SOX control testing" or "contract review" is worth far more than
   a generic one — and lives behind enterprise firewalls competitors can't reach.
3. **It's protected by the calibration interlock.** Self-improvement is only
   safe if the evaluator stays honest; `maverick.calibration` freezes learning
   when the verifier stops discriminating correct from incorrect. That's the
   guardrail that lets us learn from production *without* model collapse — and
   it's the part competitors get wrong.

**The landmine:** we have no right to learn from customer data unless the
contract grants it. The data engine is simultaneously the biggest moat and the
biggest legal liability. Getting "we may train on de-identified,
evaluator-verified, calibration-gated trajectories" into the enterprise MSA — as
a per-tenant, auditable toggle (already opt-in/scrubbed/metadata-only in
`donation.py`) — is itself a moat, because it's the clause competitors fumble.

## Is any of it *original*? (novelty check)

Honest answer from a June 2026 literature/patent sweep: **no single component is
novel.** The combination is the only differentiated ground, and even that is
heavily anticipated. Detail:

| Our mechanism | Prior art that anticipates it |
|---|---|
| Ensemble / weighted verifier voting | Weaver (weak-verifier aggregation, arXiv 2506.18203); MAV (2502.20379) |
| Verifier confidence + reward tuple → trajectory selection | Agentic Reward Modeling (2602.00575); E-valuator (2512.03109) |
| Disagreement/ensemble as a data-selection signal | Ensembles w/ regularized disagreement (2012.05825); auto-annotation quality (1910.13988) |
| Data selection as a learned/gated policy | Data Agent (2603.07433) |
| Judge calibration set / meta-evaluation | Standard FAANG practice; "shrinking the generation–verification gap" |
| Freeze-learning-on-drift, KL caps, rollback | Production-RL guardrails (Microsoft eng blog, 2026); Goodhart/KL-drift literature |

**Conclusion:** do *not* build a moat narrative on "we invented this." The
patentable surface is thin. Defensibility comes from (a) the **integration**
spanning execute → govern → evaluate → learn that no point-solution has, and
(b) the **compounding verified-domain data asset** behind an install base.
Position on defensibility, not originality — an originality claim gets laughed
out of diligence by anyone who's seen Weaver or Galileo.

## Who acquires us — and why it's not who you'd guess

Ranked by realism for *this* asset shape:

1. **Enterprise platform vendor (most likely).** ServiceNow, Salesforce, SAP,
   Workday, Microsoft. They're in a land-grab to bolt governed agents onto their
   suites and pay strategic premiums. They buy our vertical depth + the
   governance to let an agent safely write to *their* system of record; our data
   engine becomes theirs on their install base. Many such buyers = price tension.
2. **Security / governance vendor (plausible).** Palo Alto, CrowdStrike,
   Wiz/Google, Zscaler, Cisco. They buy the shield + containment + tamper-evident
   audit + "verifiable autonomy." Gap: our shield needs real detection depth +
   a threat feed to be a security *product*, not just a chokepoint.
3. **Foundation lab (cross it off).** Labs don't need our data engine (bigger
   RLAIF pipelines, generic data vendors), and training on enterprise data is
   legally radioactive for them. Building *for* a lab buyer builds the wrong
   company.

## What this means for the build

The two realistic buyers want the **same ~80% core**, so we don't have to choose
yet — we build the core and let market pull name the acquirer (see
[Design-partner scorecard](design-partner-scorecard.md)).

| Build now (shared core) | Defer to the edge the tally points to |
|---|---|
| Evaluator + verified-trajectory data engine | Platform: deep certified connectors + SoR write-back |
| Calibration interlock (keep the evaluator honest) | Platform: per-vertical pack depth + compliance mappings |
| Governance: capability attenuation, risk ceilings, human gates | Security: threat-intel feed + detection research |
| Tamper-evident audit tying *why this ran unattended* to the action | Security: adversarial/red-team eval corpus |
| SOC 2 Type II → ISO 27001 → ISO 42001 (calendar moat) | |
| Data-rights MSA clause + per-tenant donation toggle | |

## Acquisition hygiene (cheap now, deal-saving later)

- **Clean IP.** `CLA.md` + contributor assignment airtight; OSS-lite
  contributions must not contaminate the proprietary evaluator.
- **Crown-jewel boundary.** The **evaluator + eval sets + data engine** are the
  proprietary core; the swarm is the OSS-lite giveaway. Draw the license line there.
- **Kill the single-model dependency story.** Per-role routing already lets us
  swap providers — make "not betting the company on one lab" a slide; every
  acquirer probes it.
- **Certifications on the clock.** SOC 2 Type II is 6–12 months of *calendar*
  both realistic buyers require and competitors can't compress. Start now.
