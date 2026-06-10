# Sponsorship tiers — structure kit

**Roadmap ref:** 2027-H2 Distribution — "sponsorship tiers" (and 2028-H1
"sponsor tier 2" / 2028-H2 "sponsor renewal drive" build on this).
**Status:** kit complete; opening the program is the remaining operational
work. **All dollar amounts are maintainer-set** — this kit fixes the
*structure* so amounts can be slotted in without redesign.

## What sponsorship is here — and isn't

Maverick is proprietary software, so this is **not** OSS sustainability
funding. Sponsorship funds the *public goods around the product*: the free
docs, the example skills and benchmarks, community programs (office hours,
meetups, the summit), and the published safety artifacts (red-team corpus
releases, safety bulletins). Sponsors fund the ecosystem; they do not buy
the product, the roadmap, or the validation results.

Hard boundaries, stated up front in the sponsor agreement:

- **No roadmap influence.** The [roadmap](../ROADMAP.md) is re-prioritized
  on user evidence. Sponsors get the same public channels as everyone.
- **No listing shortcuts.** Sponsorship never substitutes for the
  [integration-partnership validation](./integration-partnerships.md);
  "sponsor" and "validated/certified" are independent statuses.
- **No endorsement.** We don't endorse sponsor products; logo placement is
  acknowledgment of support, nothing more. [`TRADEMARK.md`](../../TRADEMARK.md)
  applies in both directions.
- **Refusal rights.** We decline sponsors whose business conflicts with the
  product's positioning (e.g. vendors of the dark-pattern tactics the
  [stars campaign](./github-stars-campaign.md) rules out) — at the
  maintainer's sole discretion.

## Tier structure

Three tiers + an event-scoped tier. Benefits are deliberately cheap to
deliver so the program doesn't consume the engineering it funds.

| | **Supporter** | **Sponsor** | **Anchor** (cap: 3 concurrent) |
|---|---|---|---|
| Amount (annual) | _maintainer-set_ | _maintainer-set_ | _maintainer-set_ |
| Logo: docs-site sponsors page | small | medium | large |
| Logo: README sponsors section | — | ✓ | ✓ (top row) |
| Logo: summit + office-hours holding slides | — | ✓ | ✓ |
| Named in annual community survey report | ✓ | ✓ | ✓ |
| Sponsor newsletter (quarterly, what shipped + program stats) | ✓ | ✓ | ✓ |
| Conference booth co-presence (per [`conference-booth.md`](./conference-booth.md)) | — | — | ✓ |
| Invoiced, with a written agreement | ✓ | ✓ | ✓ |

**Event sponsorship** (separate, per-event): summit/meetup line items
(captioning, platform, venue, swag) offered as sponsorable units with
on-slide acknowledgment. _Amounts: maintainer-set per event budget._

"Sponsor tier 2" (2028-H1 roadmap row) is reserved for benefits that need
infrastructure that doesn't exist yet (e.g. hosted demo cluster
co-presence); don't promise those now.

## Mechanics

- **Channel:** GitHub Sponsors where it fits, direct invoice otherwise.
  _Founder decision; pick one primary channel to avoid reconciliation
  overhead._
- **Term:** 12 months, renewal not automatic (the 2028-H2 renewal drive is
  a deliberate yearly ask, with the year's program stats attached).
- **Transparency:** a public sponsors page lists every sponsor and tier.
  Money in is acknowledged; how it's spent is reported in the annual
  community survey report at line-item granularity (program costs, not
  salaries).
- **Logo hygiene:** sponsor logos appear only in the slots in the table —
  never in product UI, never in docs *content* pages, never near benchmark
  results.

## Prospect profile

Natural fits: LLM providers and inference platforms Maverick already routes
to, observability vendors with shipped self-serve integrations, sandbox/
infra vendors (container, microVM, cloud-sandbox), and enterprises that
deploy Maverick and want the ecosystem healthy. The pitch is one page:
what the money funds (the public-goods list above), the boundaries (the
no-influence list above), the tier table, last year's program stats.

## Success measure

The program pays for the community programs it exists to fund — measured
annually against the actual program costs from the year's event/meetup/
summit budgets. If sponsorship revenue exceeds program costs, bank it for
next year's programs or lower the ask; this program is not a profit center.
