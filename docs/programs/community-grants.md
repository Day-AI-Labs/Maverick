# Community grants v1 — kit

**Roadmap ref:** 2028-H1 Distribution — "community grants v1".
**Status:** kit complete; funding and opening the first cycle is the
remaining operational work. **All amounts and the annual pool are
maintainer-set; whether to fund the program at all is a founder decision**
(sponsorship revenue per [`sponsorship-tiers.md`](./sponsorship-tiers.md)
is the intended source).

Small, fixed-scope grants for community work the project wants but won't
staff: skills, plugins, docs/translations, benchmarks, meetup costs. Grants
buy *deliverables*, not time — v1 deliberately avoids becoming an
employment-shaped program.

## What's fundable (v1)

| Category | Example deliverable | Acceptance gate (existing machinery) |
|---|---|---|
| Skills | A themed skill pack | `maverick skill validate` + `python -m maverick.marketplace_moderation` APPROVE |
| Plugins (tools/channels/sandboxes) | A TS-SDK tool plugin; a sandbox backend package | `python -m maverick.plugin_matrix --ci` pass; moderation APPROVE; sandbox backends: SDK-v2 `conformance()` |
| Docs & translations | A dashboard i18n catalog; a cookbook recipe set | `i18n_portal.validate_catalog` clean / docs PR merged |
| Benchmarks & evals | Multi-seed measured rows + analysis on a `benchmarks/` harness | Rows land in `RESULTS.md` per its `measured` discipline |
| Red-team corpus | Labeled attack/benign additions | CI `redteam` job green with the additions |
| Meetup costs | A run event per [`meetups.md`](./meetups.md) | Event report + receipts |

Not fundable in v1: core-feature development (that's the roadmap and the
CLA path), marketing content, anything whose acceptance can't be checked by
an existing gate. **IP note:** upstream contributions ride the
[CLA](../../CLA.md) like any PR; standalone works (a plugin package, a
study) stay the grantee's, per the same split as
[university-outreach](./university-outreach.md) — and running Maverick to
build them requires a written evaluation license, included with the grant
award. Grants are payments for deliverables; grantees are not employees or
agents of the project.

## Application template

One page, plain text, submitted per the cycle announcement:

```
Title:
Category:            (from the fundable table)
Deliverable:         (exactly what will exist that doesn't now)
Acceptance gate:     (which check from the table proves it's done)
Amount requested:    (within the cycle's published band)
Timeline:            (≤8 weeks from award)
Who you are:         (links to prior work; no CV needed)
Why you:             (2-3 sentences)
Conflicts:           (any relationship to maintainer/judges)
```

## Review rubric

Reviewed by the maintainer + 1-2 [ambassadors](./ambassadors.md)
(conflicts recuse; reviewers can't apply in a cycle they judge). 0-2 per
row; fund top-down until the cycle pool is spent:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Scope clarity | Vague | Mostly concrete | Deliverable + gate are unambiguous |
| Value to users | Niche/duplicative | Useful | Fills a named gap (docs hole, missing channel, untested area) |
| Feasibility | Unrealistic for the timeline | Plausible | Applicant's prior work demonstrates it |
| Cost sanity | Out of band | High but arguable | Proportionate to the deliverable |
| Maintenance story | Orphan-shaped | Handoff plan | Applicant commits to one fix cycle post-acceptance |

## Mechanics

- **Cycles:** 2 per year, fixed windows (_dates founder-set_). Between
  cycles, no applications — protects review bandwidth.
- **Amounts:** a published per-grant band and per-cycle pool,
  _maintainer-set_. Keep grants small enough that a failed one is a shrug.
- **Payment:** 50% on award, 50% on the acceptance gate passing. _Payment
  rails: founder decision_ (the same rails pay award prizes and meetup
  reimbursements).
- **Failure handling:** a missed timeline gets one extension; after that
  the second tranche is simply not paid and the grant closes. No clawbacks
  of tranche one, no drama, and it doesn't bar future applications.
- **Transparency:** every cycle publishes — applications received (count),
  grants awarded (who/what/amount), and each outcome when its gate
  resolves. Anonymized rubric scores available to applicants on request.

## v1 success measure

After two cycles: ≥half of awarded grants passed their acceptance gates,
and at least one funded deliverable is in real use (installed skill,
merged catalog, cited benchmark). Below that, fix the rubric or the
categories before scaling the pool — "marketplace v3 (donate-direct
model)" on the 2028-H1 roadmap is the adjacent mechanism this program
should inform, not duplicate.
