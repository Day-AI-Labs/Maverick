# Maverick — Pitch Package (Daybreak Labs)

Fundraise and go-to-market materials for **Maverick**, the governed AI agent
workforce — built by **Daybreak Labs** (Christopher Day, Founder).

Everything here is **grounded in the real product**: every number is verifiable
with a command in this repo, or marked `[FILL]` for a founder-, customer-, or
deal-specific fact. Nothing is fabricated — it has to survive diligence.

## Three audiences

The same story, retargeted for three rooms. Same facts, different framing.

| Audience | Deck | Content source | The room |
|---|---|---|---|
| **A — Seed investor** | [`deck/audience-a.html`](./deck/audience-a.html) · 13 slides | [`SEED-DECK.md`](./SEED-DECK.md) | The raise |
| **B — Strategic acquirer** | [`deck/audience-b.html`](./deck/audience-b.html) · 12 slides | [`AUDIENCE-B.md`](./AUDIENCE-B.md) | Build-vs-buy / M&A |
| **C — First customer** | [`deck/audience-c.html`](./deck/audience-c.html) · 12 slides | [`AUDIENCE-C.md`](./AUDIENCE-C.md) | A regulated buyer's security review |

Supporting docs:

| File | What it is | Use it for |
|---|---|---|
| [`ONE-PAGER.md`](./ONE-PAGER.md) | The whole story on one page | The cold intro / forward; the leave-behind |
| [`DEMO-SCRIPT.md`](./DEMO-SCRIPT.md) | 6–8 min live runbook, exact commands + real outputs | The "show, don't tell" moment; security reviews |

See [`deck/README.md`](./deck/README.md) for how to present and export the decks.

## The proof, in four commands (all offline, no API key)

```bash
python -m maverick.golden_path -o /tmp/gp     # REFUSES the $60k wire, requires a human on $6k
python -m maverick.proof_pack  -o /tmp/pp     # SIGNS its guarantees (and refuses to fabricate)
maverick demo                                 # IMPROVES from failures — reversibly
maverick domains-lint                         # 1,118 packs, 0 errors
```

## What's still yours to fill (the `[FILL]`s)

Rendered in amber across the decks. None are things I can or should invent:

1. **The ask (A)** — amount + target pre-money. (Market default offered: ~$8–20M
   pre-money for 2026 defensible-IP seed; react to it.)
2. **Team** — your one-line bio + the "why you" / unfair insight; any co-founders
   or advisors. (Your name — Christopher Day, Founder — is already in.)
3. **Traction** — design-partner conversations, LOIs, pilots, or revenue. "Zero,
   here's the pipeline" is fine and honest.
4. **Deal / customer specifics (B / C)** — the acquirer fit and deal shape; the
   customer name, their control set, ROI, and pilot terms.
5. **Contact / data-room link.**

> **Figma:** an editable Figma rendering of Deck A exists, but still carries the
> *previous* copy — only its wordmark/footer were rebranded to Daybreak Labs. Ask
> to have it synced to the current voice and to add B/C boards.
