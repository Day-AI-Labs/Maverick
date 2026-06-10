# Foundation exploration — memo

**Roadmap ref:** 2027-H2 Distribution — "foundation exploration" (the
2028-H1 "foundation paperwork submitted" and 2028-H2 "foundation hand-off ·
governance v2 launch (elected TSC)" rows are *contingent* on this memo's
outcome — exploration may legitimately conclude "no").
**Status:** the exploration framework, complete. **The decision is the
founder's** — Maverick is solo-maintained under BDFL governance
([`MAINTAINERS.md`](../../MAINTAINERS.md)), the copyright is held by the
Licensor, and no committee output of this memo binds him.

## The honest starting point

Foundations (Linux Foundation, Apache, Eclipse model) exist primarily to
hold **open-source** assets neutrally: trademark, copyright/license
stewardship, and vendor-neutral governance. Maverick is **proprietary,
commercially licensed** software ([`LICENSE`](../../LICENSE)) whose
copyright concentration — via the [CLA](../../CLA.md) — is a deliberate
commercial asset, and whose roadmap explicitly keeps the
governance/compliance platform proprietary even if a "lite" edition ever
ships. A conventional foundation hand-off is therefore mostly *not
applicable* as-is, and this memo says so rather than pretending otherwise.

What a foundation **would** change for a proprietary product:

- **Standards neutrality.** Interop surfaces Maverick *implements* but
  shouldn't *own* — the plugin manifest format, the federation protocol
  (`maverick-federation/1`), a skill-package format — could live under
  neutral stewardship so competitors and partners adopt them without
  adopting us. (Precedent: MCP and A2A are exactly such ecosystem specs;
  Maverick deliberately adopted A2A's Agent Card and *cut* its homegrown
  equivalent — see
  [`docs/specs/a2a-vs-acd-decision.md`](../specs/a2a-vs-acd-decision.md).
  That decision is an argument for *joining* existing bodies, not founding
  one.)
- **Continuity optics.** Enterprise buyers price solo-maintainer risk. A
  body holding a continuity commitment (escrow, an LTS steward for the
  `lts/<v>` branch policy in
  [`docs/security-backports.md`](../security-backports.md)) reduces it.
  (So would a plain commercial escrow agreement, at far lower cost.)
- **Community legitimacy** for the programs in this directory — awards,
  grants, meetups gain a perception of fairness when not 100%
  founder-adjudicated.

What it would **not** change:

- **The license.** The product stays proprietary; a foundation does not and
  cannot make it community-owned. Any messaging implying otherwise would be
  the dishonesty this repo's docs exist to avoid.
- **The CLA / copyright position**, unless deliberately given up — which is
  a one-way door and a commercial decision, not a governance one.
- **The trademark**, unless transferred — [`TRADEMARK.md`](../../TRADEMARK.md)
  is owned by the Licensor; transferring the mark of a proprietary product
  to a neutral body while selling the product under it is incoherent.
- **Engineering capacity.** Paperwork creates obligations, not maintainers.

## Options

| | **A. None (status quo +)** | **B. Advisory board** | **C. Standards-only foundation involvement** |
|---|---|---|---|
| What it is | BDFL per `MAINTAINERS.md`; adopt the lightweight RFC process at 3+ maintainers as already planned; commercial escrow for continuity | 3-7 outside practitioners/customers advising on roadmap priorities and community programs; founder retains all decisions | Contribute/charter the *interop specs only* (plugin manifest, federation protocol, skill format) to an existing body (preferred) or a minimal new one; product stays out |
| Solves | Nothing new — costs nothing | Buyer-confidence optics; program-fairness optics (grants/awards adjudication) | Ecosystem adoption of surfaces we want competitors to share; spec neutrality |
| Doesn't solve | Solo-maintainer risk perception | Continuity (advice isn't succession); no legal substance | Continuity, license questions — by design |
| Cost | ~0 | Low: chartering, quarterly meetings, public minutes | Medium-high: legal, membership fees or filings, spec-editor time |
| Risk | Perception unchanged | "Advisory-washing" if the board is ignored — publish minutes or don't start | Standards capture by better-resourced members; spec velocity loss; the 2028 "hand-off" roadmap wording over-promising what C actually transfers |
| Reversible? | Yes | Yes (dissolve) | Partially — a contributed spec is contributed |

A full asset hand-off (option D, the classic foundation move) is listed only
to be rejected for now: it presupposes open-sourcing the assets handed off,
which contradicts the stated positioning. It becomes discussable only if the
"lite" edition ships *and* a strategic reason appears to neutralize it.

## Decision criteria

Score each option when the decision is actually taken (not before):

1. **Does it close a deal that's otherwise lost?** Count real evaluation
   conversations where governance/continuity was the stated blocker. Zero
   counted = option A wins by default.
2. **Does it cost engineering time the roadmap can't spare?** Anything over
   ~2 weeks/year of maintainer time needs a named benefit bigger than that.
3. **Is it honest at announcement?** If the press release would need
   careful wording to avoid implying open source or community ownership,
   the option fails as designed.
4. **Is it reversible?** Prefer reversible moves while the company is this
   small.
5. **Does an existing body already do it?** (For C: joining beats
   founding — the A2A precedent.)

## Recommendation framework

- **Default: A**, plus a commercial source-escrow offering for enterprise
  contracts (cheap, addresses the real buyer concern directly).
- **Trigger for B:** the community programs (grants, awards) reach a volume
  where founder-only adjudication is a fairness complaint actually being
  made — not preemptively.
- **Trigger for C:** a second implementation (competitor or partner) wants
  to adopt one of our interop surfaces and won't without neutrality. Until
  someone asks, a standards effort has no counterparty.
- **Re-evaluate** at each roadmap horizon or when a trigger fires; record
  the outcome as a dated decision doc under `docs/specs/` like the other
  settled decisions. If the answer stays "no", the 2028 foundation roadmap
  rows are removed with a pointer here — declining is a valid completion,
  exactly as it was for the Redis world-model and JIT decisions.

The founder decides. This memo's job is to make sure that decision is made
with the trade-offs written down, once, instead of re-argued forever.
