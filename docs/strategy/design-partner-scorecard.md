# Design-partner scorecard

> Working strategy note. The companion experiment to
> [Moat & acquisition](moat-and-acquisition.md): we can't yet name our acquirer
> profile, so we let real design-partner calls name it for us — cheaply, with a
> tally instead of a guess.

## Why this exists

The two realistic acquirers (enterprise **platform** vendor; **security /
governance** vendor) want the same ~80% core, so we don't have to bet the
roadmap on one. But the *edge* investment differs: platform → deep connectors +
system-of-record write-back; security → threat-intel feed + detection depth.
Each is a quarter of work that pays off for only one buyer.

**The signal that decides it is already arriving in your sales calls.** Count
which questions dominate. Two or three partners in, the ambiguity collapses.

## How to run it

For every design-partner / prospect call, tally each substantive question into
one bucket. Don't lead the witness — ask "what would block you from putting this
in production?" and listen.

### Bucket A — Security / governance buyer signal
- "Can it pass our security review? What's your AppSec posture?"
- "What does the shield actually catch? Show me prompt-injection / exfil coverage."
- "Show me the audit trail of every autonomous action and *why* it was allowed."
- "How do you contain a compromised agent? Kill-switch? Blast radius?"
- "Do you have SOC 2 / ISO 42001? Pen-test report? SBOM?"
- "Who can the agent act as? How is least-privilege enforced and proven?"

### Bucket B — Enterprise platform buyer signal
- "Does it integrate with our ServiceNow / Salesforce / SAP / Workday?"
- "Can it safely **write back** to records / post journal entries / update cases?"
- "Do you have a pack for *our* vertical workflow? How deep?"
- "Can business users configure agents without engineers?"
- "How does it fit our existing approval / workflow chains?"
- "What's the connector roadmap? SLAs on the integrations we depend on?"

### Bucket C — Neither (table stakes / disqualify)
Pricing, deployment model, latency, model choice. Useful, but they don't
discriminate the acquirer — don't count them.

## The scorecard (copy per call)

| Field | Value |
|---|---|
| Date / partner / industry | |
| Their current security stack (PANW/CRWD/Wiz/…?) | |
| Their current platform stack (ServiceNow/SAP/SFDC/…?) | |
| **Bucket A (security) questions** — count | |
| **Bucket B (platform) questions** — count | |
| Top blocker to production (verbatim) | |
| Champion's budget owner (CISO? platform owner? LOB?) | |

## Reading the tally

- **A ≫ B across ≥3 partners** → security/governance acquirer. Fund the threat
  feed + detection depth + certs; lead with "verifiable safe autonomy."
- **B ≫ A across ≥3 partners** → platform acquirer. Fund connectors + governed
  SoR write-back + vertical depth; lead with "the governed agent for your suite."
- **Mixed / unclear** → keep building the shared core only; do **not** fund
  either edge yet. Re-tally after the next 3 calls.
- **Second signal (corroborating):** whose tools the partner *already pays for*
  rhymes with your acquirer. A Palo Alto shop's CISO budget ≈ a security exit; a
  ServiceNow shop ≈ a platform exit.

## Decision cadence

Review the tally at every pipeline sync. The first time one bucket leads by ≥2x
over ≥3 partners, that's the call to fund the corresponding edge — and it's the
answer to "who's our acquirer" that we couldn't give upfront.
