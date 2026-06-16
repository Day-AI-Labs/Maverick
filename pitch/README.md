# Maverick — Pitch Package (Audience A: pre-seed / seed raise)

The fundraise materials. Everything here is **grounded in the real product** —
every number is verifiable with a command in this repo, or marked `[FILL]` for a
founder-only fact (the ask, the team, the traction). Nothing is fabricated; that
is deliberate, because it has to survive investor diligence.

## Contents

| File | What it is | Use it for |
|---|---|---|
| [`ONE-PAGER.md`](./ONE-PAGER.md) | The whole story on one page | The cold intro / forward; the leave-behind |
| [`SEED-DECK.md`](./SEED-DECK.md) | 13 slides: on-slide copy + speaker notes + visual direction | The meeting; the source for the visual deck |
| [`DEMO-SCRIPT.md`](./DEMO-SCRIPT.md) | 6–8 min live runbook, exact commands + real outputs | The "show, don't tell" moment; security reviews |

## The proof, in four commands (all offline, no API key)

```bash
python -m maverick.golden_path -o /tmp/gp     # it REFUSES the $60k wire, requires a human on $6k
python -m maverick.proof_pack  -o /tmp/pp     # it SIGNS its guarantees (and refuses to fabricate)
maverick demo                                 # it IMPROVES from failures — reversibly
maverick domains-lint                         # 1,118 packs, 0 errors
```

## What I still need from you (the `[FILL]`s)

These appear as `[FILL: …]` across the three docs. None of them are things I can
or should invent:

1. **The ask** — amount + target pre-money. (Market-grounded default offered:
   ~$8–20M pre-money for 2026 defensible-IP seed; react to it.)
2. **Team** — your name, one-line bio, the "why you" / unfair insight, any
   co-founders or advisors.
3. **Traction** — any design-partner conversations, LOIs, pilots, or revenue.
   "Zero, here's the pipeline" is fine and honest.
4. **Brand** — logo / colors if you have them; otherwise the deck specs a clean
   placeholder.

## Next step: the visual deck

`SEED-DECK.md` is the content source of truth. The visual build (Figma) renders:
the hero governance-chokepoint diagram (slide 3), the moat stack (6), the market
bullseye (7), and the competition table (9). Design direction is at the bottom
of `SEED-DECK.md`.
