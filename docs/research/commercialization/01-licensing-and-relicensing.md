# Licensing & Relicensing Strategy for the Maverick Commercial Pivot

> Adversarial teardown #01 (commercialization track). Date: 2026-06-06.
> Scope: what "killing OSS" can and cannot buy us, the real license menu for a
> compliance/security product, fork risk + defenses, the copyright/CLA position,
> trademark as the true lever, and a concrete recommended structure + sequence.
> Method: repo license audit (file-cited) + external precedent. Load-bearing
> external facts are inline URLs; uncertain points flagged **[verify]**.

## Bottom line

1. **You cannot "un-publish" MIT. The genie is out.** Every released version is
   already MIT under `Copyright (c) 2026 Christopher Day` (`LICENSE`), and all
   six PyPI packages carry `license = { text = "MIT" }` at `0.1.6` (`maverick-agent`,
   `maverick-channels`, `maverick-shield`, `maverick-dashboard`,
   `maverick-mcp-server`, `maverick-installer`). An MIT grant on a published work
   is irrevocable for that work — there is no clawback clause and no jurisdiction
   that lets a licensor rescind a perpetual grant already accepted. Anyone can
   `pip download maverick-agent==0.1.6`, fork it, and build a competitor from that
   tree forever. **Relicensing only ever governs *future* commits.** Plan around
   that fact, don't fight it.

2. **The right move is not "go closed." It is open-core with a source-available
   commercial layer** — because for *this* buyer (banks, hospitals, FedRAMP/air-gap,
   GRC teams replacing OneTrust), **source visibility is a sales asset, not a
   liability**: auditability, self-host, and "read the code that governs your
   agents" are exactly the trust signals the compliance positioning sells (per
   `docs/research/regulated-deployment-and-compliance-platform.md`, Part 4 — "self-host
   as the moat"). Going dark would destroy the differentiator you're pivoting *toward*.

3. **The enforceable moat is the trademark, not the license.** The code is forkable;
   the name "Maverick," the marks, and the right to say "the official build" are not.
   That is the lever — and today there is **no trademark notice anywhere in the repo**
   (grep for `trademark|™|®` across `*.md`/`*.toml` is negative).

## What "killing OSS" can and cannot achieve

**Can:** stop *future* proprietary value (the governance control plane, hosted
multi-tenant SaaS, framework-content library, enterprise connectors) from being
free; force commercial users onto a paid relationship for new releases; let you
add anti-SaaS-reseller terms going forward.

**Cannot:** retract the MIT grant on `<=0.1.6`; prevent a fork of that snapshot;
prevent third parties from continuing to distribute the old versions; "make the
code private" — it is mirrored, on PyPI, and likely already cloned. The only
defenses against a fork are *velocity* (out-run it), *trademark* (it can't be
called Maverick), and *the commercial layer never being open in the first place*.

## The real options (hard comparison for a compliance/security product)

| Option | What it is | Fit for compliance buyer | Fork/relicense risk | Verdict |
|---|---|---|---|---|
| **Fully proprietary, closed going forward** | New code closed; binaries only | **Bad** — kills auditability/self-host trust; FedRAMP/air-gap reviewers want source | Low fork-of-new, but max community/credibility loss | Reject |
| **Open-core** (permissive core + proprietary commercial modules) | Kernel stays OSS; control plane is a separate closed/commercial package | **Strong** — core stays auditable; you charge for the governance/SaaS surface | Core forkable (already is); commercial layer never open ⇒ not forkable | **Recommend (combine w/ below)** |
| **Source-available — BSL 1.1** | Source published, use restricted (typically "no competing hosted service"), converts to OSS after N years | **Strong** — buyers *read* the source, can self-host; blocks AWS-style resale | Forks of the pre-BSL MIT snapshot remain; see HashiCorp→OpenTofu | **Recommend for the commercial layer** |
| **Source-available — Elastic v2 (ELv2)** | Permissive-ish but bans "provide as a managed service" + no license-circumvention/trademark-strip | Good; simpler than BSL, no time-bomb conversion | Forks remain; see OpenSearch | Viable alternative to BSL |
| **Source-available — FSL (Functional Source License)** | Sentry's license: blocks *competing* commercial use for 2 years, then converts to Apache-2.0/MIT | **Strong** — narrowest restriction, most "almost-open," developer-friendly | Low; very fork-resistant in practice (narrow ban) | **Strong fit, see rec** |
| **SSPL** | MongoDB's copyleft-on-steroids: offering as a service obligates open-sourcing your *entire* service stack | Poor here — OSI rejects it as non-open, enterprises' legal/procurement increasingly *blocklist* it | Forks remain (AWS DocumentDB / Amazon ran from older MongoDB) | **Reject** — toxic to enterprise procurement |

Sources: BSL <https://mariadb.com/bsl11/>, HashiCorp adoption
<https://www.hashicorp.com/blog/hashicorp-adopts-business-source-license>; Elastic v2
<https://www.elastic.co/licensing/elastic-license>; FSL <https://fsl.software/>,
Sentry rationale <https://blog.sentry.io/sentry-license-change/>; SSPL
<https://www.mongodb.com/legal/licensing/server-side-public-license>; OSI on SSPL
<https://opensource.org/blog/the-sspl-is-not-an-open-source-license>.

**Why source-available beats both poles here:** closed forfeits the audit/self-host
trust the pivot is built on; permissive lets a hyperscaler resell your governance
plane. BSL/FSL/ELv2 keep the source readable and self-hostable (what the buyer
values) while denying the one thing you must — a competitor running it as a service.

## Fork risk + defenses (precedents)

The pivot's central risk: a relicense triggers a community fork off the last
permissive commit. It has happened every time a notable project did this:

- **Terraform → OpenTofu** (HashiCorp BSL, Aug 2023): Linux-Foundation fork,
  broad adoption. <https://opentofu.org/> — the canonical "relicense backfire."
- **Redis → Valkey** (SSPL/RSALv2, Mar 2024): Linux Foundation + AWS/Google fork;
  Redis later *reverted* to add AGPL in 2025. <https://valkey.io/>
- **Elasticsearch → OpenSearch** (SSPL/ELv2, 2021): AWS-led fork now broadly
  packaged. <https://opensearch.org/>
- **CockroachDB** moved fully to its proprietary CockroachDB Software License in
  2024 (dropped the BSL-with-conversion). <https://www.cockroachlabs.com/blog/enterprise-license-update/> **[verify exact terms/date]**

**Defenses that actually work:**
1. **Trademark** — forks must rename (OpenTofu, Valkey, OpenSearch all had to). Your
   strongest lever; see below.
2. **Keep the *commercial* layer out of the permissive tree entirely** — you can't
   fork what was never published open. The control plane is born source-available, never MIT.
3. **Velocity + the data/network moat** — a compliance product's value is in
   certifications (SOC 2/ISO 42001/FedRAMP ATO), the regulatory-content corpus, the
   hosted control plane, and signed-evidence integrations — *none of which a code fork
   inherits.* Forking the kernel gets you a kernel, not a certified compliance business.
   This is why open-core is low-risk *here specifically.*
4. **Don't surprise the community** — phased and documented, kernel left genuinely
   usable. Backlash above was sharpest where the relicense rug-pulled the *whole*
   product, not a new commercial tier.

## Copyright, CLA, and AI-authored commits

- **Christopher Day owns essentially all copyright.** Git history shows no external
  human contributors, no CLA, no DCO. `LICENSE` names a single holder.
  Consequence: **relicensing *future* code needs no contributor sign-off** — the sole
  author can release new versions under any terms. (Contrast the projects above,
  which had to either own copyright or rely on inbound=outbound license terms.)
- **"Claude"/AI-authored commits do not create third-party copyright.** Under
  current US law, purely AI-generated material is not copyrightable and creates no
  authorship interest a third party could assert (US Copyright Office,
  *Copyright and Artificial Intelligence* guidance, 2025
  <https://www.copyright.gov/ai/>; *Thaler v. Perlmutter*). So AI commits do **not**
  cloud the relicensing right. **Nuance [verify with counsel]:** (a) human-edited AI
  output can carry human authorship in the edits — here that's still *your* authorship,
  so it's fine; (b) the more real risk is **provenance of any code the model
  reproduced from training data** under a copyleft license — a model-hygiene/IP-scan
  question, independent of the relicense; (c) the current `CONTRIBUTING.md` "by
  contributing, you agree your contributions are licensed under the same terms [MIT]"
  is an inbound=outbound clause — fine while solo, but it must be **replaced** before
  reopening contributions (next section), or new inbound code is locked to MIT.

## Trademark as the real enforcement lever

The license governs copying; the **trademark** governs *calling it Maverick*. This
is the durable moat and it is currently unguarded:
- **No `™`/`®`/trademark notice or policy exists in the repo.** Add a `TRADEMARK.md`
  and notices; **file a USPTO application** for "Maverick" (and the logo) in the
  relevant IT/SaaS classes (likely Class 9 + 42) **[verify availability — "Maverick"
  is a common word; the mark may need to be the full product/wordmark or a stylized
  form, and clearance search is essential]**.
- Publish a trademark-use policy: forks may use the code (per license) but **may not
  use the name or imply official status**. This is exactly what forced OpenTofu/
  Valkey/OpenSearch to rebrand and is what protects "the official, certified build."
- For a compliance product the mark is doubly load-bearing: certifications (SOC 2,
  FedRAMP ATO) attach to *your entity and your named product*, not to a fork.

## Going-forward DCO/CLA (if contributions ever reopen)

If/when external contributions are accepted again, the current inbound=outbound-MIT
clause is wrong for a commercial product — it would force new inbound code to be MIT
and could pollute the source-available layer. Options:
- **DCO (sign-off)** — lightweight provenance attestation (`Signed-off-by`),
  no rights transfer; insufficient alone if you need to dual-license.
- **CLA (recommended for the commercial repo)** — a contributor *license* (or
  copyright-assignment) agreement granting you the right to relicense/dual-license
  inbound contributions, so the open-core boundary stays clean. Apache ICLA-style is
  the norm. (HashiCorp/Elastic/MongoDB all run CLAs precisely to preserve relicensing
  freedom.) Note the `lint-pr-title` CI already enforces process discipline; adding a
  CLA-bot gate is consistent with house rule 6 (the wizard/process is source of truth).

## What to relicense vs keep permissive

Map onto the existing architecture (`packages/`):

- **Keep permissive (MIT/Apache-2.0) — the kernel as an adoption funnel:**
  `maverick-core` agent kernel, `maverick-shield` (CLAUDE.md rule 1: kernel runs
  without the shield; it's a fail-open chokepoint, ideal as free/open),
  `maverick-channels`, `maverick-mcp-server`, the installer/SDK, examples. These drive
  PyPI installs, community, and the "auditable runtime" trust. **Consider Apache-2.0
  for new permissive code** (explicit patent grant — better than MIT for an enterprise
  product) **[verify desire to change permissive license vs. staying MIT for continuity]**.
- **Born source-available / commercial — the governance control plane (the product):**
  the multi-tenant hosted control plane, the AI/agent **registry + framework-mapped
  evidence export**, the regulatory-content library, SSO/SCIM + KMS enterprise
  modules, and the OneTrust-replacing compliance workflows (Phases 1–3 of the
  compliance doc). These are the Q2 product; they should **never enter the MIT tree**.
  License them FSL or BSL 1.1.

This is the open-core line: the *runtime* others can read and self-host stays
permissive (and forkable — accept that); the *governance business* is source-available
and trademark-protected.

## What would kill us

- **Going fully closed** — forfeits the auditability/self-host trust that *is* the
  compliance differentiator; reviewers (FedRAMP/air-gap) and security buyers walk.
- **Picking SSPL** — enterprise procurement and legal increasingly blocklist it;
  it poisons exactly the deals you're chasing, and still doesn't stop the snapshot fork.
- **A rug-pull relicense of the *whole* product** — guarantees a Terraform→OpenTofu-style
  fork *with* community sympathy. Relicense only the new commercial layer; keep the
  kernel genuinely open.
- **Leaving the trademark unregistered** — without the mark you have *no* enforceable
  lever over a fork; the license alone can't stop a competitor (it can be forked).
- **Reopening contributions on inbound=outbound MIT** — silently locks new code to
  MIT and can contaminate the source-available layer; you lose dual-licensing freedom.
- **Forgetting the irrevocability math** — any plan that assumes old versions can be
  pulled is built on sand. They can't.

## Recommendations

1. **Adopt open-core + source-available, not closed.** Kernel & adapters stay
   permissive (evaluate Apache-2.0 for new permissive code); the governance control
   plane is **born source-available under FSL** (Sentry's license: blocks competing
   commercial/hosted use for 2 years, then converts to Apache-2.0 — narrowest
   restriction, best developer goodwill, strong fork resistance). Fall back to **BSL
   1.1** if you need an explicit "no competing managed service" grant with a longer
   change window. **Reject SSPL and fully-proprietary.**
2. **Make trademark the enforcement lever now.** Clearance-search and file "Maverick"
   (wordmark + logo) with the USPTO **[verify mark availability]**; add `TRADEMARK.md`
   + notices + a use policy ("fork the code, not the name"). This is the real moat.
3. **Never publish the commercial layer under MIT.** Open-core's safety is that the
   governance plane was never open — keep it in a separate, source-available repo/package
   from day one.
4. **Swap the contribution terms before reopening.** Replace the inbound=outbound-MIT
   clause with a CLA granting relicensing rights (DCO at minimum), gated in CI.
5. **Migration sequence:**
   (a) Freeze: the last MIT release stays MIT forever — say so plainly, it builds trust.
   (b) Re-license-forward only the *new* commercial modules (FSL/BSL); leave the kernel MIT.
   (c) File the trademark + publish the policy *before* announcing, so forks can't grab the name.
   (d) Replace CONTRIBUTING terms with a CLA; add CLA-bot gate.
   (e) Announce as "new commercial governance tier," **not** "Maverick is no longer open" —
       the framing decides whether you get OpenTofu'd.
   (f) Keep kernel velocity high so any snapshot fork falls behind on its own.

*Cross-references: business-model fork (A/B/C) in
`docs/research/regulated-deployment-and-compliance-platform.md` Part 6; positioning
in `docs/ROADMAP.md` ("open-source-only, no paid tiers" — the line this pivot
deliberately breaks).*
