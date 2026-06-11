# Regional meetups — playbook

**Roadmap ref:** 2028-H1 Distribution — "regional meetup playbook".
**Status:** playbook complete; the first meetup happening is the remaining
operational work. **Per-event budget support: maintainer-set.**

Small, recurring, organizer-led technical evenings — not mini-conferences.
A meetup with 8 engineers and a live terminal beats 80 people and a pitch
deck. Organizers are typically [ambassadors](./ambassadors.md), but anyone
can run one under this playbook.

## Format that works (2 hours)

| Minutes | Block |
|---|---|
| 0-20 | Doors + setup; the demo loop running on a screen |
| 20-30 | Welcome: what Maverick is in 5 minutes (handbook one-pager), what shipped lately (`CHANGELOG.md`) |
| 30-60 | One prepared talk: a real deployment, a built skill/plugin, or a module deep-dive — showcase-wall evidence standard preferred ([`showcase.md`](../showcase.md)) |
| 60-90 | Live workshop block: attendees install (`pipx install 'maverick-agent[installer]'`, `maverick init --fast`) and run a first goal with `maverick monitor` open; organizers float |
| 90-115 | Open discussion / show-and-tell |
| 115-120 | Pointers: docs, office hours, how to host the next one |

Workshop notes: have the [getting-started](../getting-started.md) page up,
expect venue Wi-Fi to fail (a phone-hotspot fallback and an offline Ollama
demo machine cover it), and remind people the runtime spends real API money —
`--max-dollars` on everything, or local models.

## Organizer checklist

- [ ] Venue: free/cheap (office space, university room); seats, screen,
      power. No bar-only venues — laptops are the point.
- [ ] Listing: any events platform or a repo discussion thread; the listing
      states it's a community event, [CoC](../../CODE_OF_CONDUCT.md)
      linked and enforced (organizer is the contact).
- [ ] Naming/trademark: "Maverick Meetup <City>" is permitted nominative
      use **with written permission per [`TRADEMARK.md`](../../TRADEMARK.md)**
      — request it once when registering the meetup (below); no logo
      remixes, no implying official-company status.
- [ ] Content: claims policy applies (capabilities per
      [`FEATURES.md`](../FEATURES.md); roadmap labeled as roadmap; no
      open-source promises; license questions answered honestly:
      proprietary, evaluation via the licensor contact).
- [ ] Speakers: one is enough; recruit from attendees for next time.
- [ ] Photos only with room consent; no attendee list leaves the room.

## What the project provides

Register a meetup by opening an issue titled `meetup: <city>`. Registered
organizers get:

- This playbook, the talk-starter deck (maintainer-provided once assets
  exist), and the demo-loop script from the
  [booth kit](./conference-booth.md) stations 1-3.
- Trademark permission letter for the meetup name.
- Listing on the docs-site community page + mention at office hours.
- Swag pack per [`swag.md`](./swag.md) while stocks exist.
- Cost support per event (pizza/printing tier): **maintainer-set cap**,
  reimbursed against receipts via the
  [community-grants](./community-grants.md) rails. No venue rental or
  travel funding in v1.

## What the project does not provide

Speakers on demand, paid promotion, alcohol budget, or exclusivity (two
meetups in one city is fine; they'll merge or won't).

## Cadence + health

Recommended: quarterly per city; monthly only if it sustains itself.
A city series is healthy when: it has ≥2 organizers (bus factor), repeat
attendees, and a local talk pipeline. Report after each event (one
paragraph + headcount in the meetup issue) keeps the listing active;
two unreported cycles moves the city to dormant — undramatically, like a
stale partner listing.
