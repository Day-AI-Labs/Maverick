# What we take from Palantir (and what we don't)

Palantir's enterprise-AI credibility rests on *governed, traceable, operational*
software. That instinct maps cleanly onto Lightwork's wedge — **provable, governed,
self-improving agents** — so we borrow Palantir's *concepts* at agent scale, while
deliberately **not** trying to become a data-integration company.

## The trap to avoid
Palantir's true moat is the **Ontology + data integration** — the brutal work of
unifying an organization's data estate into one semantic+operational model. That
is a different company and a different decade of work. We take the *idea* (typed
actions, lineage, simulate-before-commit), **not** the data-OS scope.

## What we borrowed — and where it now lives

| Palantir concept | Lightwork borrow | In the code |
|---|---|---|
| Ontology **Actions** (typed, permissioned operations) | Typed `ActionSpec` registry — declared ops, not free-form calls | `maverick/governed_actions.py` |
| **Simulate / branch** before commit | `simulate()` previews an effect with no side effects; commit gated on risk/approval | `governed_actions.py` (`Preview`) |
| **Lineage** ("trace this number to source") | Tamper-evident, hash-chained lineage of every committed action → inputs, sources, skills | `governed_actions.py` (`verify_lineage`, `trace`) |
| **Act on systems of record** (CRM/ticketing/ERP) | A `Connector` surface exposing `<sys>.read` (low risk) / `<sys>.write` (high risk → approval) as governed Actions | `maverick/governed_connectors.py` |
| **Forward-Deployed Engineer** GTM | Land on one painful workflow with a tailored pack + measured ROI, then expand | this doc (below) |

All of it is **opt-in and additive**: the kernel does not route through these by
default, so shipping them changes nothing out of the box. They compose with what
already existed — `RISK_LEVELS`/`risk_rank` (`safety/tool_risk.py`), the
provenance-chain hash pattern, the signed audit chain, and the Operating Record.

### Why this is *more* defensible than imitating Palantir
Palantir governs *data and the actions on it*. Lightwork governs *the same — plus
the agent's learning*: a learned skill carries provenance, the learning is signed
and revocable, and now every consequential **action** is typed, previewed, and
lineage-traced. The pitch is **"Palantir-grade trust, for self-improving agents"**
— lead with the thing Palantir doesn't have (auditable learning), not the thing it
owns (the data OS).

## The Forward-Deployed playbook (GTM borrow)

Palantir lands by embedding engineers in a customer's hardest operational problem,
proving value, then expanding. We do the same **lighter** — the pack/suite library
is the leverage Palantir solves with a services army.

1. **Pick one painful, measurable workflow** (e.g. tier-1 ticket triage, claims
   intake, vendor onboarding). Not "AI for the enterprise" — *this* workflow.
2. **Ship a tailored pack** from the 26-suite library, plus 1–2 governed
   Connectors to the systems that workflow touches (read first, write behind the
   approval gate).
3. **Run it governed from day one**: simulate-before-commit on every write, lineage
   on every action, the Operating Record as the audit surface. The buyer's risk
   team is a champion, not a blocker.
4. **Measure ROI on that workflow** (cost/throughput/error-rate vs. the manual
   baseline) — the same honest, bounded measurement discipline we hold the moat to.
5. **Expand by suite, not by promise**: the *next* workflow reuses the same
   governed-action + connector substrate, and — uniquely — the agent is *cheaper
   and more reliable on classes it has seen*, with the audit trail to prove it.

### What to resist
- **No bespoke data-integration projects.** If a deal needs us to become the
  customer's data platform, that's the wrong deal.
- **No services-led margins.** The packs + governed substrate are what keep this
  product-led; protect that.
