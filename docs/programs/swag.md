# Swag — spec + production kit

**Roadmap ref:** 2027-H2 Distribution — "swag store".
**Status:** kit complete; choosing a vendor and placing the order is the
remaining operational work. **Quantities, budget, and store-vs-giveaway
model are founder decisions.**

One constraint shapes everything: **the official logo/wordmark assets are
not yet published** (the [press kit](../press-kit.md) marks them as
placeholders to be added by maintainers). Producing branded goods is blocked
on those assets landing; text-only designs below can proceed without them.
The marks are trademarks of the Licensor ([`TRADEMARK.md`](../../TRADEMARK.md))
— swag is produced only by/for the project, never licensed to third parties
to print.

## Design specs (described; final art is a maintainer deliverable)

Tone: engineer-dry, claims-true. Nothing on a shirt we couldn't defend in a
code review. No hype slogans.

| Item | Design description |
|---|---|
| **T-shirt A — "the command"** | Front: small wordmark on the chest. Back: a single mono-spaced line — `maverick start "do the whole thing"` — nothing else. Dark shirt, light ink |
| **T-shirt B — "governed"** | Front: wordmark. Back, mono-spaced, three stacked lines: `budget.check()` / `sandbox.exec()` / `audit verify` — the three primitives, each a real call/verb in the runtime |
| **Sticker pack (die-cut, 3 designs)** | (1) logo mark alone *(blocked on assets)*; (2) text badge `governed · audited · self-hosted`; (3) mono `~/.maverick/HALT` — the killswitch file, the insider joke that's also a real feature |
| **Terminal mug** | Wrap-around mono print of a real (trimmed) `maverick monitor` plan-tree frame — sourced from an actual run's TUI output, secrets none by construction |
| **Laptop sleeve sticker — "Built with Maverick"** | Reserved for the [badge program](./badge-program.md): given to verified showcase-wall entrants, not handed out loose, so it stays a signal |
| **Speaker/contributor gift** | Higher-grade item (e.g. embroidered wordmark on a quality hoodie) reserved for summit speakers, ambassadors, and merged-PR contributors — scarcity is the point |

Explicitly out: anything with capability claims ("the most X agent"),
competitor mentions, or invented numbers.

## Production checklist

- [ ] **Assets gate:** final logo/wordmark (SVG, light + dark) merged into
      the repo and the press-kit placeholders resolved. _Owner: maintainer._
- [ ] Trademark sanity: every design uses the marks per `TRADEMARK.md`;
      file copies of final art in the repo's asset location once it exists.
- [ ] Proof pass: print a single proof of each item before any bulk order;
      check ink on dark fabric and mono-font legibility at distance.
- [ ] Vendor selection (_founder decision_): prefer print-on-demand for the
      store model (zero inventory) and a bulk run only for known events;
      get unit + shipping costs in writing.
- [ ] Sizing: order curves weighted to real event data after the first
      conference; default to a standard curve before data exists.
- [ ] Quantities + budget: _maintainer-set_; the booth kit and summit
      speaker list are the demand inputs.
- [ ] Fulfillment model (_founder decision_): (a) giveaway-only at events —
      simplest; (b) at-cost print-on-demand store — no margin, no inventory,
      no fulfillment labor; (c) priced store — only worth it if (b) shows
      real demand. Recommendation: start at (a), add (b) on request volume.
- [ ] Compliance basics for a store: printed-on-demand goods, vendor handles
      tax/shipping; we never collect payment data ourselves.

## Distribution rules

- Free at events while stocks last; no "star the repo for a shirt"
  ([stars-campaign rules](./github-stars-campaign.md) apply to swag too).
- Contributor/speaker gifts are sent, not requested.
- The "Built with Maverick" sticker ships only with a verified badge
  ([`badge-program.md`](./badge-program.md)).

## Measurement

Swag is brand surface, not a funnel — don't pretend to measure conversions.
Track only: cost per item, items distributed per event, and reorder
interest. If nobody asks where to get one after two events, the designs are
wrong; revise before reordering.
