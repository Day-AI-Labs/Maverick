# Integration partnerships — business kit

**Roadmap ref:** 2027-H1 Distribution — "integration partnerships (business
half; self-serve guide shipped)". The technical half already exists:
[`docs/integrations/observability-partners.md`](../integrations/observability-partners.md)
documents the self-serve paths (OpenRouter as a provider, OTLP-generic
tracing, base_url overrides). This kit is the *relationship* half: what a
named partnership means, what an integration must pass, and where the
marketing boundaries sit. **Fees (if any), SLA numbers, and the partner
roster are founder decisions** — marked below.

Two principles, non-negotiable:

1. **Self-serve stays free and open to everyone.** A vendor never needs a
   partnership to integrate — the protocols (MCP, OTLP, OpenAI-compatible
   `base_url`, the plugin SDKs) are documented and available. A partnership
   adds validation, support commitments, and co-marketing; it never gates
   the integration surface itself.
2. **Listing is earned by passing checks, not by paying.** A partner that
   fails the technical validation below is not listed, whatever the
   business relationship.

## Partner tiers

| | **Tier 0 — Self-serve** (not a partnership) | **Tier 1 — Validated** | **Tier 2 — Certified** |
|---|---|---|---|
| Who | Anyone | Vendor with a maintained integration | Vendor with a maintained integration + support commitment |
| Agreement | None | Lightweight letter (validation + listing terms) | Signed partnership agreement |
| Technical bar | Works for their users | Passes the validation checklist below, re-run per Lightwork minor release | Tier 1 + signed artifacts + a named technical contact + the reliability drill |
| Listing | None implied | Row in the relevant integrations doc, "validated against vX.Y" | Row marked certified + entry in release-notes compatibility table |
| Co-marketing | Nominative use only ([`TRADEMARK.md`](../../TRADEMARK.md)) | Joint blog post permitted (boundaries below) | Tier 1 + joint webinar/booth presence permitted |
| Support | Community channels | Shared issue-triage expectations (below) | Cross-escalation path with response-time commitments |
| Fee | Free | _Founder decision (recommendation: free — the validation work is the cost)_ | _Founder decision_ |

Keep the roster small. Five well-maintained Tier 1/2 partners beat fifty
logos; the breadth-vs-depth decision
([`docs/specs/breadth-vs-depth-decision.md`](../specs/breadth-vs-depth-decision.md))
applies to partnerships too.

## Technical-validation checklist

What "validated" means, concretely. The partner runs these and submits the
output; we re-run them before listing. Everything here is shipped tooling —
no bespoke certification harness.

### All integrations

- [ ] **Works against a tagged release** (not `main`), version recorded in
      the listing.
- [ ] **No license violation**: the integration drives Lightwork over public
      surfaces (MCP, gRPC, REST, plugin SDKs, `base_url`); it does not
      redistribute, embed, or fork Lightwork code — that requires a separate
      commercial license from the Licensor ([`LICENSE`](../../LICENSE)).
- [ ] **Honest claims**: the partner's own marketing describes only what the
      integration does; Lightwork capability claims must be grounded in
      [`FEATURES.md`](../FEATURES.md).

### Plugin-shaped integrations (tools, channels, sandbox backends)

- [ ] **Plugin compatibility matrix passes** — `python -m
      maverick.plugin_matrix --ci` (the same gate CI runs): the plugin
      declares a supported API major, loads, and isn't refused. Plugin API
      v2 rules apply ([`docs/plugin-api-v2.md`](../plugin-api-v2.md)):
      manifest permissions declared and enforced.
- [ ] **Moderation checks pass** — `python -m maverick.marketplace_moderation
      <path>` returns APPROVE (FLAG findings resolved with a reviewer;
      REJECT is disqualifying): manifest completeness, no undeclared
      subprocess/network/env access, no embedded secrets, no prohibited
      patterns, license declared.
- [ ] **Signed artifacts** (Tier 2 required, Tier 1 recommended) — either
      sigstore keyless signing (`python -m maverick.sigstore_signing
      sign|verify`, identity+issuer pinned) or a publisher cert from the
      self-hosted plugin CA (`plugin_ca.py`); installs must verify
      fail-closed.
- [ ] **Lockfile-clean** — `maverick plugin lock` then `maverick plugin
      verify` reports no drift on a fresh install.
- [ ] **Isolation-compatible** — the plugin behaves under
      `[plugins] isolation = "subprocess"` (no reliance on host env secrets
      or shared globals).
- [ ] **Reliability drill** (Tier 2, long-running plugins) — `python -m
      maverick.plugin_reliability` properties hold: crash recovery, fault
      isolation, bounded error rate, no monotonic memory growth.
- [ ] **Sandbox backends additionally**: conform to the Sandbox SDK v2
      protocol (`maverick/sandbox/sdk.py` `conformance()`) and load via the
      `maverick.sandboxes` entry-point group.

### Provider / observability integrations

- [ ] Provider adapters: format-translation tests in the partner's CI
      against recorded fixtures (the `FakeLLM` pattern — never live keys in
      CI), per CONTRIBUTING "Adding a provider".
- [ ] Observability: traces verified to carry the OTel GenAI
      semantic-convention attributes Lightwork emits (see Observability in
      `FEATURES.md`) — the partner maps nothing custom.

### Re-validation cadence

Per Lightwork **minor** release, the partner re-runs the checklist within
30 days or the listing gains a "last validated: vX.Y" staleness note; two
missed cycles delists. The deprecation registry (`python -m
maverick.deprecations`) tells partners what's sunsetting and when.

## Co-marketing boundaries

What a partner may and may not do, by tier. The trademark policy
([`TRADEMARK.md`](../../TRADEMARK.md)) governs everything; this is the
application of it.

**Any tier (including non-partners):**

- May state factually: "works with Lightwork", "integrates with Lightwork" —
  nominative use.
- May **not** use the Lightwork name/logo in their product name, domain,
  package name, or advertising; may not imply endorsement, affiliation, or
  "official" status; may not publish Lightwork benchmark claims that aren't
  measured rows in `benchmarks/RESULTS.md`.

**Tier 1 adds:** "validated for Lightwork vX.Y" wording (exact phrase set by
us), one joint blog post per validation cycle (we review claims before
publication; review SLA: 5 business days), listing in our integrations docs.

**Tier 2 adds:** "certified" wording, joint webinars, shared conference
presence (see [`conference-booth.md`](./conference-booth.md)), quote
exchange for press (subject to the press-kit claims policy in
[`press-and-case-studies.md`](./press-and-case-studies.md)).

**Never, at any tier:** logo placement implying co-ownership, "powered by
Lightwork" for products that merely connect to it, exclusivity claims,
case-study claims without the evidence table from the case-study template,
or any statement that Lightwork is or will be open source.

## Support & SLA expectations

Numbers marked _founder-set_ go in the signed agreement, not this doc.

| Obligation | Tier 1 | Tier 2 |
|---|---|---|
| Named technical contact each side | Recommended | Required |
| Cross-filed bug triage (acknowledge + route) | Best effort | _Founder-set response time (recommendation: 2 business days)_ |
| Security issues affecting the integration | Per [`SECURITY.md`](../../SECURITY.md), both directions | Same, plus direct contact exchange |
| Breaking-change notice from us | Public deprecation registry + release notes | Same + direct heads-up at deprecation time, before removal |
| Breaking-change notice from partner | Listing-staleness process above | _Founder-set advance notice (recommendation: 30 days)_ |
| End-customer support | Each party supports its own product; no joint support desk | Same — joint support is explicitly out of scope for v1 |

What we do **not** promise partners: roadmap influence (the
[roadmap](../ROADMAP.md) is re-prioritized on user evidence, not partner
requests), private API surfaces, or exclusivity.

## Running the program

1. Inbound or targeted outbound (the observability-partners doc already
   names the natural first conversations). Track candidates in a private
   list — no public "coming soon" partner pages.
2. Partner runs the checklist self-serve; submits artifacts.
3. We re-run validation (budget: ≤1 engineer-day per partner per cycle).
4. Founder signs the tier agreement; listing lands by PR like any other
   docs change.
5. Quarterly: review the roster against the re-validation cadence; delist
   stale rows without drama.
